import numpy as np
import pytest
from PIL import Image

from vigia.overlay import Layer, draw_layers

SIZE = (400, 300)  # width, height
INSIDE = (220, 170)  # x, y: inside the mask, away from its outline
OUTSIDE = (380, 280)
RED_ON_GRAY = (178, 50, 50)  # gray 100 blended 50/50 with pure red


def gray_image(value=100):
    return Image.new("RGB", SIZE, (value, value, value))


def square_mask(shape=(300, 400), top=150, left=200, size=40):
    mask = np.zeros(shape, dtype=bool)
    mask[top:top + size, left:left + size] = True
    return mask


def test_mask_pixels_are_tinted_with_the_layer_color():
    out = draw_layers(gray_image(), [Layer(mask=square_mask(), color=(255, 0, 0), label="plume")], alpha=0.5)

    assert out.getpixel(INSIDE) == RED_ON_GRAY


def test_pixels_outside_every_mask_are_unchanged():
    out = draw_layers(gray_image(), [Layer(mask=square_mask(), color=(255, 0, 0), label="plume")])

    assert out.getpixel(OUTSIDE) == (100, 100, 100)


def test_labels_never_cover_the_mask():
    layer = Layer(mask=square_mask(top=0, left=0), color=(255, 0, 0), label="plume")

    out = draw_layers(gray_image(), [layer], alpha=0.5)

    assert out.getpixel((5, 8)) == RED_ON_GRAY  # where a label anchored at the mask's corner would go


def test_output_keeps_the_input_size_and_does_not_modify_the_input():
    image = gray_image()

    out = draw_layers(image, [Layer(mask=square_mask(), color=(0, 255, 0), label="steam")])

    assert out.size == image.size
    assert image.getpixel(INSIDE) == (100, 100, 100)


def test_mask_with_a_different_shape_than_the_image_is_rejected():
    with pytest.raises(ValueError, match="shape"):
        draw_layers(gray_image(), [Layer(mask=square_mask(shape=(10, 10), top=0, left=0, size=3), color=(0, 0, 255), label="x")])
