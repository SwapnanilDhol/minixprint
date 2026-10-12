#!/usr/bin/env python3
"""Render a sample restaurant receipt to receipt.png (384 px wide) and print it."""
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
import subprocess, sys

W = 384
mono = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 17)
bold = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", 17, index=1)
big  = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 34, index=1)
cw = mono.getlength("0")                    # monospace char width
COLS = int((W - 8) // cw)                   # chars per line

items = [("Masala Dosa", 2, 180.0), ("Filter Coffee", 2, 60.0),
         ("Paneer Butter Masala", 1, 320.0), ("Butter Naan", 3, 45.0),
         ("Gulab Jamun", 1, 90.0)]
sub = sum(q*p for _, q, p in items); cgst = sgst = round(sub*0.025, 2); total = sub + cgst + sgst

lines = []                                  # (text, font, align)
def L(t="", f=mono, a="l"): lines.append((t, f, a))
def row(left, right, f=mono): L(left[:COLS-len(right)-1].ljust(COLS-len(right)) + right, f)
def rule(ch="-"): L(ch*COLS)

L("DOSA & CO.", big, "c"); L("South Indian Kitchen", mono, "c"); L("12 MG Road, Bengaluru 560001", mono, "c")
L("GSTIN 29ABCDE1234F1Z5", mono, "c"); L()
rule("=")
row("Bill #1042", datetime.now().strftime("%d %b %Y %H:%M")); row("Table 7", "Server: Priya")
rule("=")
row("ITEM", "QTY   AMOUNT", bold); rule()
for name, q, p in items: row(name, f"{q:>3} {q*p:>9.2f}")
rule()
row("Subtotal", f"{sub:9.2f}"); row("CGST 2.5%", f"{cgst:9.2f}"); row("SGST 2.5%", f"{sgst:9.2f}")
rule("="); row("TOTAL", f"INR {total:,.2f}", bold); rule("=")
L(); L("Paid: UPI  ****4821", mono, "c"); L(); L("Thank you! Visit again", bold, "c"); L("dosaandco.in", mono, "c"); L()

lh = 22; H = sum(lh if f is not big else 44 for _, f, _ in lines) + 16
img = Image.new("1", (W, H), 1); d = ImageDraw.Draw(img); y = 8
for t, f, a in lines:
    h = 44 if f is big else lh
    x = 4 if a == "l" else (W - f.getlength(t)) / 2
    d.text((x, y), t, font=f, fill=0); y += h
img.save("receipt.png"); print("rendered", img.size, f"{COLS} cols")
if "--print" in sys.argv: subprocess.run([sys.executable, "minix.py", "image", "receipt.png"], check=True)
