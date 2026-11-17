#!/usr/bin/env python3
"""Make the QR code pictures used by the reel promo slide (needs:  pip install "qrcode[pil]").

    python tools/make_qr.py https://target1st.in/products/hrn-hi/ assets/qr-notes.png
    python tools/make_qr.py https://prep.target1st.in/app/haryana-group-d assets/qr-mocks.png

The picture is a plain black-on-white QR with a quiet border (scans best). build.py reads assets/qr-notes.png and
assets/qr-mocks.png by default; other pictures can be set in the JSON meta "promo_items".
"""
import sys

import qrcode
from qrcode.constants import ERROR_CORRECT_M

if len(sys.argv) != 3:
    sys.exit(__doc__)
qr = qrcode.QRCode(error_correction=ERROR_CORRECT_M, box_size=14, border=2)
qr.add_data(sys.argv[1])
qr.make(fit=True)
qr.make_image(fill_color="#111111", back_color="#ffffff").save(sys.argv[2])
print(f"saved {sys.argv[2]} for {sys.argv[1]}")
