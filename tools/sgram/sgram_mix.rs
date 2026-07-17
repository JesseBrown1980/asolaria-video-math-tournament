// sgram_mix.rs — STREAMING (SGRAM) variant of hp_mix.
//
// The MODEL (logistic context mixing, order-0..4 + bias) and the fpaq0-derived
// arithmetic CODER are copied VERBATIM from hp_mix.rs. ONLY the file I/O is
// changed: compress reads the input in fixed blocks and flushes coded bytes to
// disk incrementally; decompress decodes streaming and writes output in blocks.
// The model is already online/causal, so the coded bitstream is byte-identical
// to the non-streaming mix — proven by the IDENTICAL-ARCHIVE test.
//
// Modes:
//   compress   <in> <archive>   : 8-byte LE length header (from fs metadata) + AC stream
//   decompress <archive> <out>  : reconstruct byte-exact, streamed
//   sverify    <in>             : stream-compress to a temp archive, then stream-
//                                 decompress while running sha256 on both input and
//                                 reconstruction; never holds full input/output in RAM.
//
// Report row:
//   SGRAM|mode=..|input_bytes=..|archive_bytes=..|decoder_src_bytes=..|bpc=..|roundtrip_exact=..|json=0

use std::env;
use std::fs;
use std::fs::File;
use std::io::{BufReader, BufWriter, Read, Write};
use std::process::exit;

// ---------------------------------------------------------------------------
// squash / stretch (logistic <-> 12-bit probability), lpaq tables.  VERBATIM.
// ---------------------------------------------------------------------------
#[inline]
fn squash(d: i32) -> i32 {
    const T: [i32; 33] = [
        1, 2, 3, 6, 10, 16, 27, 45, 73, 120, 194, 310, 488, 747, 1101, 1546, 2047,
        2549, 2994, 3348, 3607, 3785, 3901, 3975, 4022, 4050, 4068, 4079, 4085,
        4089, 4092, 4093, 4094,
    ];
    if d > 2047 { return 4095; }
    if d < -2047 { return 0; }
    let w = d & 127;
    let idx = ((d >> 7) + 16) as usize;
    (T[idx] * (128 - w) + T[idx + 1] * w + 64) >> 7
}

fn build_stretch() -> Vec<i32> {
    let mut stretch = vec![0i32; 4096];
    let mut pi: i32 = 0;
    for x in -2047..=2047 {
        let p = squash(x);
        while pi <= p {
            stretch[pi as usize] = x;
            pi += 1;
        }
    }
    while (pi as usize) < 4096 {
        stretch[pi as usize] = 2047;
        pi += 1;
    }
    stretch
}

// ---------------------------------------------------------------------------
// MODEL — VERBATIM from hp_mix.rs.
// ---------------------------------------------------------------------------
const NIN: usize = 6;
const O0SIZE: usize = 256;
const O1SIZE: usize = 1 << 16;
const HSIZE: usize = 1 << 22;
const MC: usize = 256;
const RATE: i32 = 4;
const LR_SHIFT: i32 = 12;
const WCLAMP: i32 = 1 << 24;

struct Model {
    t0: Vec<u16>,
    t1: Vec<u16>,
    t2: Vec<u16>,
    t3: Vec<u16>,
    t4: Vec<u16>,
    w: Vec<i32>,
    c1: u32,
    c2: u32,
    c3: u32,
    c4: u32,
    h2: u32,
    h3: u32,
    h4: u32,
    idx: [usize; 5],
    st: [i32; NIN],
    wctx: usize,
    pr: i32,
    stretch: Vec<i32>,
}

#[inline]
fn hidx(h: u32, node: u32, size: usize) -> usize {
    let x = (h ^ node.wrapping_mul(0x9E37_79B1)).wrapping_mul(0x2545_F491);
    (x as usize) & (size - 1)
}

impl Model {
    fn new() -> Self {
        let mut w = vec![0i32; MC * NIN];
        let init = (65536 / 5) as i32;
        for c in 0..MC {
            for i in 0..5 {
                w[c * NIN + i] = init;
            }
        }
        Model {
            t0: vec![2048u16; O0SIZE],
            t1: vec![2048u16; O1SIZE],
            t2: vec![2048u16; HSIZE],
            t3: vec![2048u16; HSIZE],
            t4: vec![2048u16; HSIZE],
            w,
            c1: 0,
            c2: 0,
            c3: 0,
            c4: 0,
            h2: 0,
            h3: 0,
            h4: 0,
            idx: [0; 5],
            st: [0; NIN],
            wctx: 0,
            pr: 2048,
            stretch: build_stretch(),
        }
    }

    #[inline]
    fn predict(&mut self, node: u32) -> u32 {
        self.idx[0] = (node as usize) & (O0SIZE - 1);
        self.idx[1] = (((self.c1 << 8) | node) as usize) & (O1SIZE - 1);
        self.idx[2] = hidx(self.h2, node, HSIZE);
        self.idx[3] = hidx(self.h3, node, HSIZE);
        self.idx[4] = hidx(self.h4, node, HSIZE);

        let p0 = self.t0[self.idx[0]] as usize;
        let p1 = self.t1[self.idx[1]] as usize;
        let p2 = self.t2[self.idx[2]] as usize;
        let p3 = self.t3[self.idx[3]] as usize;
        let p4 = self.t4[self.idx[4]] as usize;

        self.st[0] = self.stretch[p0];
        self.st[1] = self.stretch[p1];
        self.st[2] = self.stretch[p2];
        self.st[3] = self.stretch[p3];
        self.st[4] = self.stretch[p4];
        self.st[5] = 256;

        self.wctx = (self.c1 as usize) & (MC - 1);
        let base = self.wctx * NIN;
        let mut dot: i64 = 0;
        for i in 0..NIN {
            dot += (self.st[i] as i64) * (self.w[base + i] as i64);
        }
        let mut d = (dot >> 16) as i32;
        if d > 2047 { d = 2047; }
        if d < -2047 { d = -2047; }
        let mut p = squash(d);
        if p < 1 { p = 1; }
        if p > 4094 { p = 4094; }
        self.pr = p;
        p as u32
    }

    #[inline]
    fn update(&mut self, bit: u32) {
        let target = (bit as i32) << 12;
        {
            let t = &mut self.t0[self.idx[0]];
            let pr = *t as i32;
            *t = (pr + ((target - pr) >> RATE)) as u16;
        }
        {
            let t = &mut self.t1[self.idx[1]];
            let pr = *t as i32;
            *t = (pr + ((target - pr) >> RATE)) as u16;
        }
        {
            let t = &mut self.t2[self.idx[2]];
            let pr = *t as i32;
            *t = (pr + ((target - pr) >> RATE)) as u16;
        }
        {
            let t = &mut self.t3[self.idx[3]];
            let pr = *t as i32;
            *t = (pr + ((target - pr) >> RATE)) as u16;
        }
        {
            let t = &mut self.t4[self.idx[4]];
            let pr = *t as i32;
            *t = (pr + ((target - pr) >> RATE)) as u16;
        }
        let err = target - self.pr;
        let base = self.wctx * NIN;
        for i in 0..NIN {
            let mut nw = self.w[base + i] + ((self.st[i] * err) >> LR_SHIFT);
            if nw > WCLAMP { nw = WCLAMP; }
            if nw < -WCLAMP { nw = -WCLAMP; }
            self.w[base + i] = nw;
        }
    }

    #[inline]
    fn push_byte(&mut self, b: u8) {
        self.c4 = self.c3;
        self.c3 = self.c2;
        self.c2 = self.c1;
        self.c1 = b as u32;
        self.h2 = self
            .c1
            .wrapping_mul(0x6B43_A9B5)
            .wrapping_add(self.c2.wrapping_add(1).wrapping_mul(0x9E37_79B1));
        self.h3 = self
            .h2
            .wrapping_mul(0x2545_F491)
            .wrapping_add(self.c3.wrapping_add(1).wrapping_mul(0x85EB_CA77));
        self.h4 = self
            .h3
            .wrapping_mul(0x2545_F491)
            .wrapping_add(self.c4.wrapping_add(1).wrapping_mul(0xC2B2_AE35));
    }
}

// ---------------------------------------------------------------------------
// Arithmetic coder — coding logic COPIED VERBATIM from hp_mix.rs; only the
// byte SINK/SOURCE is changed from Vec/&[u8] to a streamed buffer (I/O only).
// The bytes emitted (and their order) are unchanged, so archives are identical.
// ---------------------------------------------------------------------------
const IOBUF: usize = 1 << 16;

struct Encoder<W: Write> {
    x1: u32,
    x2: u32,
    w: W,
    buf: Vec<u8>,
}
impl<W: Write> Encoder<W> {
    fn new(w: W) -> Self {
        Encoder { x1: 0, x2: 0xFFFF_FFFF, w, buf: Vec::with_capacity(IOBUF) }
    }
    #[inline]
    fn emit(&mut self, b: u8) {
        self.buf.push(b);
        if self.buf.len() >= IOBUF {
            self.w.write_all(&self.buf).expect("write archive");
            self.buf.clear();
        }
    }
    #[inline]
    fn encode(&mut self, bit: u32, p: u32) {
        let range = self.x2 - self.x1;
        let xmid = self.x1 + (range >> 12) * p;
        if bit == 1 { self.x2 = xmid; } else { self.x1 = xmid + 1; }
        while (self.x1 ^ self.x2) & 0xFF00_0000 == 0 {
            let b = (self.x2 >> 24) as u8;
            self.emit(b);
            self.x1 <<= 8;
            self.x2 = (self.x2 << 8) | 0xFF;
        }
    }
    fn flush(&mut self) {
        for _ in 0..4 {
            let b = (self.x1 >> 24) as u8;
            self.emit(b);
            self.x1 <<= 8;
        }
        if !self.buf.is_empty() {
            self.w.write_all(&self.buf).expect("write archive");
            self.buf.clear();
        }
        self.w.flush().expect("flush archive");
    }
}

struct Decoder<R: Read> {
    x1: u32,
    x2: u32,
    x: u32,
    r: R,
    buf: Vec<u8>,
    pos: usize,
    len: usize,
}
impl<R: Read> Decoder<R> {
    fn new(mut r: R) -> Self {
        let mut buf = vec![0u8; IOBUF];
        let len = r.read(&mut buf).expect("read archive");
        let mut d = Decoder { x1: 0, x2: 0xFFFF_FFFF, x: 0, r, buf, pos: 0, len };
        for _ in 0..4 { d.x = (d.x << 8) | d.next() as u32; }
        d
    }
    #[inline]
    fn next(&mut self) -> u8 {
        if self.pos >= self.len {
            self.len = self.r.read(&mut self.buf).expect("read archive");
            self.pos = 0;
            if self.len == 0 {
                return 0; // past EOF: matches original slice behavior (reads 0)
            }
        }
        let b = self.buf[self.pos];
        self.pos += 1;
        b
    }
    #[inline]
    fn decode(&mut self, p: u32) -> u32 {
        let range = self.x2 - self.x1;
        let xmid = self.x1 + (range >> 12) * p;
        let bit = if self.x <= xmid { 1 } else { 0 };
        if bit == 1 { self.x2 = xmid; } else { self.x1 = xmid + 1; }
        while (self.x1 ^ self.x2) & 0xFF00_0000 == 0 {
            self.x1 <<= 8;
            self.x2 = (self.x2 << 8) | 0xFF;
            self.x = (self.x << 8) | self.next() as u32;
        }
        bit
    }
}

// ---------------------------------------------------------------------------
// Streaming compress / decompress.
// ---------------------------------------------------------------------------
fn compress_stream(in_path: &str, archive_path: &str) -> (u64, u64) {
    let n: u64 = fs::metadata(in_path).expect("stat input").len();
    let fin = File::open(in_path).expect("open input");
    let mut reader = BufReader::with_capacity(IOBUF, fin);
    let fout = File::create(archive_path).expect("create archive");
    let mut writer = BufWriter::with_capacity(IOBUF, fout);
    writer.write_all(&n.to_le_bytes()).expect("write header"); // 8-byte LE length

    let mut m = Model::new();
    let mut e = Encoder::new(&mut writer);
    let mut block = vec![0u8; 8 * 1024 * 1024]; // 8 MiB block
    loop {
        let got = reader.read(&mut block).expect("read input");
        if got == 0 { break; }
        for &byte in &block[..got] {
            let mut node: u32 = 1;
            for i in (0..8).rev() {
                let bit = ((byte >> i) & 1) as u32;
                let p = m.predict(node);
                e.encode(bit, p);
                m.update(bit);
                node = (node << 1) | bit;
            }
            m.push_byte(byte);
        }
    }
    e.flush();
    writer.flush().expect("flush");
    let archive_len = fs::metadata(archive_path).expect("stat archive").len();
    (n, archive_len)
}

fn decompress_stream(archive_path: &str, out_path: &str) -> (u64, u64) {
    let fin = File::open(archive_path).expect("open archive");
    let mut reader = BufReader::with_capacity(IOBUF, fin);
    let mut hdr = [0u8; 8];
    reader.read_exact(&mut hdr).expect("read header");
    let n = u64::from_le_bytes(hdr) as usize;

    let fout = File::create(out_path).expect("create output");
    let mut writer = BufWriter::with_capacity(IOBUF, fout);

    let mut m = Model::new();
    let mut d = Decoder::new(&mut reader);
    let mut obuf: Vec<u8> = Vec::with_capacity(IOBUF);
    for _ in 0..n {
        let mut node: u32 = 1;
        for _ in 0..8 {
            let p = m.predict(node);
            let bit = d.decode(p);
            m.update(bit);
            node = (node << 1) | bit;
        }
        let byte = (node & 0xFF) as u8;
        obuf.push(byte);
        if obuf.len() >= IOBUF {
            writer.write_all(&obuf).expect("write output");
            obuf.clear();
        }
        m.push_byte(byte);
    }
    if !obuf.is_empty() { writer.write_all(&obuf).expect("write output"); }
    writer.flush().expect("flush output");
    let out_len = fs::metadata(out_path).expect("stat output").len();
    (n as u64, out_len)
}

// ---------------------------------------------------------------------------
// Minimal dep-free SHA-256 (streaming).
// ---------------------------------------------------------------------------
struct Sha256 {
    h: [u32; 8],
    len: u64,
    buf: [u8; 64],
    buflen: usize,
}
impl Sha256 {
    fn new() -> Self {
        Sha256 {
            h: [
                0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19,
            ],
            len: 0,
            buf: [0u8; 64],
            buflen: 0,
        }
    }
    fn update(&mut self, mut data: &[u8]) {
        self.len = self.len.wrapping_add(data.len() as u64);
        if self.buflen > 0 {
            let need = 64 - self.buflen;
            let take = need.min(data.len());
            self.buf[self.buflen..self.buflen + take].copy_from_slice(&data[..take]);
            self.buflen += take;
            data = &data[take..];
            if self.buflen == 64 {
                let block = self.buf;
                self.process(&block);
                self.buflen = 0;
            }
        }
        while data.len() >= 64 {
            let mut block = [0u8; 64];
            block.copy_from_slice(&data[..64]);
            self.process(&block);
            data = &data[64..];
        }
        if !data.is_empty() {
            self.buf[..data.len()].copy_from_slice(data);
            self.buflen = data.len();
        }
    }
    fn process(&mut self, block: &[u8; 64]) {
        const K: [u32; 64] = [
            0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1,
            0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
            0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786,
            0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
            0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147,
            0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
            0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b,
            0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
            0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a,
            0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
            0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
        ];
        let mut wv = [0u32; 64];
        for i in 0..16 {
            wv[i] = u32::from_be_bytes([
                block[i * 4], block[i * 4 + 1], block[i * 4 + 2], block[i * 4 + 3],
            ]);
        }
        for i in 16..64 {
            let s0 = wv[i - 15].rotate_right(7) ^ wv[i - 15].rotate_right(18) ^ (wv[i - 15] >> 3);
            let s1 = wv[i - 2].rotate_right(17) ^ wv[i - 2].rotate_right(19) ^ (wv[i - 2] >> 10);
            wv[i] = wv[i - 16]
                .wrapping_add(s0)
                .wrapping_add(wv[i - 7])
                .wrapping_add(s1);
        }
        let mut a = self.h[0];
        let mut b = self.h[1];
        let mut c = self.h[2];
        let mut d = self.h[3];
        let mut e = self.h[4];
        let mut f = self.h[5];
        let mut g = self.h[6];
        let mut hh = self.h[7];
        for i in 0..64 {
            let s1 = e.rotate_right(6) ^ e.rotate_right(11) ^ e.rotate_right(25);
            let ch = (e & f) ^ ((!e) & g);
            let t1 = hh.wrapping_add(s1).wrapping_add(ch).wrapping_add(K[i]).wrapping_add(wv[i]);
            let s0 = a.rotate_right(2) ^ a.rotate_right(13) ^ a.rotate_right(22);
            let maj = (a & b) ^ (a & c) ^ (b & c);
            let t2 = s0.wrapping_add(maj);
            hh = g;
            g = f;
            f = e;
            e = d.wrapping_add(t1);
            d = c;
            c = b;
            b = a;
            a = t1.wrapping_add(t2);
        }
        self.h[0] = self.h[0].wrapping_add(a);
        self.h[1] = self.h[1].wrapping_add(b);
        self.h[2] = self.h[2].wrapping_add(c);
        self.h[3] = self.h[3].wrapping_add(d);
        self.h[4] = self.h[4].wrapping_add(e);
        self.h[5] = self.h[5].wrapping_add(f);
        self.h[6] = self.h[6].wrapping_add(g);
        self.h[7] = self.h[7].wrapping_add(hh);
    }
    fn finalize(mut self) -> [u8; 32] {
        let bitlen = self.len.wrapping_mul(8);
        let mut pad = [0u8; 72];
        pad[0] = 0x80;
        let padlen = if self.buflen < 56 { 56 - self.buflen } else { 120 - self.buflen };
        self.update_no_len(&pad[..padlen]);
        let lb = bitlen.to_be_bytes();
        self.update_no_len(&lb);
        let mut out = [0u8; 32];
        for i in 0..8 {
            out[i * 4..i * 4 + 4].copy_from_slice(&self.h[i].to_be_bytes());
        }
        out
    }
    // like update but does not add to self.len (used for padding)
    fn update_no_len(&mut self, mut data: &[u8]) {
        if self.buflen > 0 {
            let need = 64 - self.buflen;
            let take = need.min(data.len());
            self.buf[self.buflen..self.buflen + take].copy_from_slice(&data[..take]);
            self.buflen += take;
            data = &data[take..];
            if self.buflen == 64 {
                let block = self.buf;
                self.process(&block);
                self.buflen = 0;
            }
        }
        while data.len() >= 64 {
            let mut block = [0u8; 64];
            block.copy_from_slice(&data[..64]);
            self.process(&block);
            data = &data[64..];
        }
        if !data.is_empty() {
            self.buf[..data.len()].copy_from_slice(data);
            self.buflen = data.len();
        }
    }
}

fn hex(b: &[u8; 32]) -> String {
    let mut s = String::with_capacity(64);
    for &x in b.iter() {
        s.push_str(&format!("{:02x}", x));
    }
    s
}

fn sha256_file(path: &str) -> [u8; 32] {
    let f = File::open(path).expect("open for sha");
    let mut r = BufReader::with_capacity(IOBUF, f);
    let mut sh = Sha256::new();
    let mut buf = vec![0u8; 8 * 1024 * 1024];
    loop {
        let got = r.read(&mut buf).expect("read for sha");
        if got == 0 { break; }
        sh.update(&buf[..got]);
    }
    sh.finalize()
}

// Streaming decompress that computes sha256 of the reconstruction WITHOUT
// materializing the whole output. Writes nothing to disk.
fn decompress_sha(archive_path: &str) -> ([u8; 32], u64) {
    let fin = File::open(archive_path).expect("open archive");
    let mut reader = BufReader::with_capacity(IOBUF, fin);
    let mut hdr = [0u8; 8];
    reader.read_exact(&mut hdr).expect("read header");
    let n = u64::from_le_bytes(hdr) as usize;

    let mut m = Model::new();
    let mut d = Decoder::new(&mut reader);
    let mut sh = Sha256::new();
    let mut obuf: Vec<u8> = Vec::with_capacity(IOBUF);
    for _ in 0..n {
        let mut node: u32 = 1;
        for _ in 0..8 {
            let p = m.predict(node);
            let bit = d.decode(p);
            m.update(bit);
            node = (node << 1) | bit;
        }
        let byte = (node & 0xFF) as u8;
        obuf.push(byte);
        if obuf.len() >= IOBUF {
            sh.update(&obuf);
            obuf.clear();
        }
        m.push_byte(byte);
    }
    if !obuf.is_empty() { sh.update(&obuf); }
    (sh.finalize(), n as u64)
}

fn decoder_src_bytes() -> u64 {
    fs::metadata(file!()).map(|m| m.len()).unwrap_or(0)
}

// ---------------------------------------------------------------------------
// main / CLI
// ---------------------------------------------------------------------------
fn main() {
    let a: Vec<String> = env::args().collect();
    if a.len() < 3 {
        eprintln!("usage: sgram_mix <compress|decompress|sverify> <in> [out]");
        exit(2);
    }
    match a[1].as_str() {
        "compress" => {
            if a.len() < 4 { eprintln!("usage: sgram_mix compress <in> <archive>"); exit(2); }
            let (input, archive) = compress_stream(&a[2], &a[3]);
            let dsrc = decoder_src_bytes();
            let bpc = if input > 0 { (archive as f64 * 8.0) / input as f64 } else { 0.0 };
            println!(
                "SGRAM|mode=compress|input_bytes={}|archive_bytes={}|decoder_src_bytes={}|bpc={:.4}|roundtrip_exact=|json=0",
                input, archive, dsrc, bpc
            );
        }
        "decompress" => {
            if a.len() < 4 { eprintln!("usage: sgram_mix decompress <archive> <out>"); exit(2); }
            let (n, out) = decompress_stream(&a[2], &a[3]);
            let arc = fs::metadata(&a[2]).expect("stat archive").len();
            println!(
                "SGRAM|mode=decompress|input_bytes={}|archive_bytes={}|decoder_src_bytes={}|bpc=|roundtrip_exact=|json=0",
                out, arc, decoder_src_bytes()
            );
            let _ = n;
        }
        "sverify" => {
            let in_path = &a[2];
            // temp archive on disk, alongside the input.
            let tmp = format!("{}.sgram.tmp", in_path);
            let (input, archive) = compress_stream(in_path, &tmp);
            // pass 1: sha256 of original input (streamed, no full-file RAM)
            let in_hash = sha256_file(in_path);
            // pass 2: streamed decode of temp archive -> running sha256, no full output RAM
            let (out_hash, out_len) = decompress_sha(&tmp);
            let _ = fs::remove_file(&tmp);
            let exact = (in_hash == out_hash && out_len == input) as u32;
            let bpc = if input > 0 { (archive as f64 * 8.0) / input as f64 } else { 0.0 };
            let dsrc = decoder_src_bytes();
            eprintln!("sverify: input_sha256={}", hex(&in_hash));
            eprintln!("sverify: recon_sha256={}", hex(&out_hash));
            println!(
                "SGRAM|mode=sverify|input_bytes={}|archive_bytes={}|decoder_src_bytes={}|bpc={:.4}|roundtrip_exact={}|json=0",
                input, archive, dsrc, bpc, exact
            );
            if exact != 1 { eprintln!("ROUNDTRIP_FAIL"); exit(1); }
        }
        _ => { eprintln!("unknown mode"); exit(2); }
    }
}
