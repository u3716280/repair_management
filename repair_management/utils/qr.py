import pyqrcode


def get_qr_code(value, scale=4):
    if not value:
        return ""

    qr = pyqrcode.create(str(value))

    return qr.png_as_base64_str(
        scale=scale,
        quiet_zone=2
    )
