#!/usr/bin/env python3
# Replit-ready solver for "Senior-lucky_but_unlucky"
# Connects to nc 110.164.135.99 10002, collects MT19937 outputs,
# reconstructs state, predicts next values, sends correct lucky-name,
# and tries a few number-answer patterns to retrieve: flag{message_10digits}

import socket
import time
import re
import sys
from typing import Optional, Tuple, List

HOST = "110.164.135.99"
PORT = 10002

# --------- MT19937 predictor utilities ---------
U, D = 11, 0xFFFFFFFF
S, B = 7,  0x9D2C5680
T, C = 15, 0xEFC60000
L = 18

def undo_right_shift_xor(y: int, shift: int) -> int:
    x = 0
    for i in range(0, 32, shift):
        part = y >> i
        mask = ((1 << shift) - 1) if i + shift <= 32 else ((1 << (32 - i)) - 1)
        x_part = (part ^ (x >> shift)) & mask
        x |= x_part << i
    return x & 0xFFFFFFFF

def undo_left_shift_xor_and(y: int, shift: int, mask: int) -> int:
    x = 0
    for i in range(0, 32, shift):
        part_mask = ((1 << shift) - 1) if i + shift <= 32 else ((1 << (32 - i)) - 1)
        part = (y >> i) & part_mask
        prev = (x << shift) & mask
        x_part = part ^ ((prev >> i) & part_mask)
        x |= x_part << i
    return x & 0xFFFFFFFF

def untemper(y: int) -> int:
    y &= 0xFFFFFFFF
    y = undo_right_shift_xor(y, L)
    y = undo_left_shift_xor_and(y, T, C)
    y = undo_left_shift_xor_and(y, S, B)
    y = undo_right_shift_xor(y, U)
    return y & 0xFFFFFFFF

class MT19937:
    N = 624
    M = 397
    MATRIX_A = 0x9908B0DF
    UPPER_MASK = 0x80000000
    LOWER_MASK = 0x7FFFFFFF

    def __init__(self):
        self.mt = [0] * self.N
        self.index = self.N

    def seed_from_state(self, state_untempered: List[int]):
        if len(state_untempered) != self.N:
            raise ValueError("Need exactly 624 untempered values")
        self.mt = [x & 0xFFFFFFFF for x in state_untempered]
        self.index = self.N  # ensure twist on next generate

    def twist(self):
        for i in range(self.N):
            y = (self.mt[i] & self.UPPER_MASK) | (self.mt[(i + 1) % self.N] & self.LOWER_MASK)
            self.mt[i] = (self.mt[(i + self.M) % self.N] ^ (y >> 1))
            if (y & 1) != 0:
                self.mt[i] ^= self.MATRIX_A
            self.mt[i] &= 0xFFFFFFFF
        self.index = 0

    @staticmethod
    def temper(y: int) -> int:
        y ^= (y >> U)
        y ^= (y << S) & B
        y ^= (y << T) & C
        y ^= (y >> L)
        return y & 0xFFFFFFFF

    def next_uint32(self) -> int:
        if self.index >= self.N:
            self.twist()
        y = self.mt[self.index]
        self.index += 1
        return self.temper(y)

# --------- Networking helpers ---------
def recv_all(sock: socket.socket, timeout: float = 2.0) -> str:
    sock.settimeout(timeout)
    chunks = []
    try:
        while True:
            data = sock.recv(4096)
            if not data:
                break
            chunks.append(data.decode(errors="ignore"))
            if len(data) < 4096:
                # small wait & peek
                time.sleep(0.05)
                try:
                    peek = sock.recv(1, socket.MSG_PEEK)
                    if not peek:
                        break
                except socket.timeout:
                    break
    except socket.timeout:
        pass
    return "".join(chunks)

def connect_once() -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5.0)
    s.connect((HOST, PORT))
    return s

re_exit  = re.compile(r"Exit\s*#\s*(\d+)", re.IGNORECASE)
re_lucky = re.compile(r"Lucky\s*#\s*(\d+)", re.IGNORECASE)
re_flag  = re.compile(r"flag\{[^\}]+\}", re.IGNORECASE)

def one_fail_round() -> Tuple[Optional[int], Optional[int], str]:
    """
    Make one connection, intentionally fail (send dummy name),
    and parse 'Exit #<x>' and 'Lucky #<lucky>'.
    """
    s = connect_once()
    out = ""
    lucky_val = None
    exit_val = None
    try:
        out += recv_all(s, timeout=1.0)

        # send a throwaway name
        try:
            s.sendall(b"nope\n")
            time.sleep(0.05)
            s.sendall(b"\n")
        except Exception:
            pass

        out += recv_all(s, timeout=2.0)

        m_exit  = re_exit.search(out)
        m_lucky = re_lucky.search(out)
        if m_exit:
            exit_val = int(m_exit.group(1))
        if m_lucky:
            lucky_val = int(m_lucky.group(1))

    finally:
        try:
            s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        s.close()

    return lucky_val, exit_val, out

def collect_outputs(target_count: int = 624) -> List[int]:
    """
    Collect tempered 32-bit outputs in generator order: lucky first, then exit.
    Each fail-round should yield a pair; loop until we have target_count values.
    """
    outputs: List[int] = []
    rounds = 0
    while len(outputs) < target_count:
        rounds += 1
        lucky_val, exit_val, out = one_fail_round()
        if lucky_val is None or exit_val is None:
            print(f"[collect] round {rounds}: parse failed, have {len(outputs)}/{target_count}")
            time.sleep(0.15)
            continue

        outputs.append(lucky_val & 0xFFFFFFFF)
        if len(outputs) < target_count:
            outputs.append(exit_val & 0xFFFFFFFF)

        if rounds % 10 == 0 or len(outputs) % 50 == 0:
            print(f"[collect] round {rounds}: total {len(outputs)}/{target_count}")
            sys.stdout.flush()

    return outputs[:target_count]

def try_number_sequences(s: socket.socket):
    """
    Try a few number-answer patterns to satisfy typical numeric checks.
    Sequences are separated by tiny delays; harmless if not needed.
    """
    # ASCII digits
    seqs = [
        ["0", "0"],
        ["1", "0"],
        ["0", "1"],
        ["1", "1"],
    ]
    # Unicode math digits (often pass isdigit() but dodge naive filters)
    uni0 = "𝟘"
    uni1 = "𝟙"
    seqs += [
        [uni0, uni0],
        [uni1, uni0],
        [uni0, uni1],
        [uni1, uni1],
    ]

    for pair in seqs:
        for item in pair:
            s.sendall((item + "\n").encode("utf-8"))
            time.sleep(0.05)
        # small wait to see if flag appears after a pair
        time.sleep(0.1)

def final_attack(predictor: MT19937) -> Optional[str]:
    """
    Predict next lucky and x, send 'lucky<x>' as name, then try number sequences.
    Return flag if printed.
    """
    next_lucky = predictor.next_uint32()
    next_x = predictor.next_uint32()

    s = connect_once()
    flag_found = None
    try:
        welcome = recv_all(s, timeout=1.0)

        # Send predicted lucky-name
        name_line = f"lucky{next_x}\n"
        s.sendall(name_line.encode())

        # Try various numeric answers
        time.sleep(0.1)
        try_number_sequences(s)

        # Read everything and look for flag
        final_out = recv_all(s, timeout=3.0)
        combined = (welcome or "") + final_out
        m = re_flag.search(combined)
        if m:
            flag_found = m.group(0)

        print("=== FINAL INTERACTION OUTPUT ===")
        print(combined)
        print("=== END OUTPUT ===")

    finally:
        try:
            s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        s.close()

    return flag_found

def main():
    print(f"[i] Connecting to {HOST}:{PORT} and collecting 624 MT outputs (about 300+ quick rounds)...")
    outputs = collect_outputs(624)
    print("[i] Collected 624 outputs. Reconstructing MT state...")

    state_untempered = [untemper(y) for y in outputs]
    predictor = MT19937()
    predictor.seed_from_state(state_untempered)
    print("[i] State reconstructed. Launching final attack...")

    flag = final_attack(predictor)
    if flag:
        print(f"[SUCCESS] {flag}")
    else:
        print("[!] Flag not found in the final output.")
        print("    Check the FINAL INTERACTION OUTPUT above; if you share it, I can tweak the responses quickly.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[!] Interrupted by user.")
