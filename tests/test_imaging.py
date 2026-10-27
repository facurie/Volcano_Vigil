import io

from PIL import Image

from vigia.imaging import load_for_upload


def test_load_for_upload_caps_the_longest_side_and_encodes_jpeg(tmp_path):
    path = tmp_path / "wide.png"
    Image.new("RGB", (4096, 1024), (90, 90, 90)).save(path)

    image, jpeg = load_for_upload(path, max_side=2048)

    assert image.size == (2048, 512)
    with Image.open(io.BytesIO(jpeg)) as sent:
        assert (sent.format, sent.size) == ("JPEG", (2048, 512))


def test_load_for_upload_keeps_small_frames_at_full_size(tmp_path):
    path = tmp_path / "small.jpg"
    Image.new("RGB", (640, 480)).save(path)

    image, _ = load_for_upload(path)

    assert image.size == (640, 480)


def test_load_for_upload_applies_the_exif_rotation(tmp_path):
    path = tmp_path / "portrait.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90° clockwise to display
    Image.new("RGB", (400, 300)).save(path, exif=exif)

    image, _ = load_for_upload(path)

    assert image.size == (300, 400)
