"""Genera pepper.ico (32x32) - faccina robot, senza dipendenze."""
import struct, math, os

W = H = 32
NAVY = (0x0c, 0x23, 0x40)   # RGB
ACC = (0x2f, 0x7b, 0xff)
CX, CY, R = 15.5, 16.5, 15.0

def px(x, y):
    dx, dy = x - CX, y - CY
    d = math.hypot(dx, dy)
    if d > R:
        return (0, 0, 0, 0)  # trasparente
    # occhi
    for ex in (11, 20):
        if math.hypot(x - ex, y - 14) <= 3.2:
            return (ACC[2], ACC[1], ACC[0], 255)  # BGRA
    # bocca (sorriso): banda curva
    if 20 <= y <= 24 and abs((y - 20) - (2 - abs(x - 15.5) * 0.35)) < 1.2 and 8 <= x <= 23:
        return (ACC[2], ACC[1], ACC[0], 255)
    return (NAVY[2], NAVY[1], NAVY[0], 255)

# pixel bottom-up
xor = bytearray()
for row in range(H - 1, -1, -1):
    for col in range(W):
        xor += bytes(px(col, row))
and_mask = bytes(4 * H)  # tutto 0

bmih = struct.pack('<IiiHHIIiiII', 40, W, H * 2, 1, 32, 0, 0, 0, 0, 0, 0)
img = bmih + bytes(xor) + and_mask
entry = struct.pack('<BBBBHHII', W, H, 0, 0, 1, 32, len(img), 22)
ico = struct.pack('<HHH', 0, 1, 1) + entry + img

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pepper.ico")
with open(out, "wb") as f:
    f.write(ico)
print("icona creata:", out, len(ico), "byte")
