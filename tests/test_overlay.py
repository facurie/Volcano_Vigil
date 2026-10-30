import numpy as np
import pytest
from PIL import Image

from vigil.overlay import Layer, draw_layers

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


def layer(color=(255, 0, 0), label="plume", **mask_args):
    return Layer(mask=square_mask(**mask_args), color=color, label=label)


def test_mask_pixels_are_tinted_with_the_layer_color():
    out = draw_layers(gray_image(), [layer()], alpha=0.5)

    assert out.getpixel(INSIDE) == RED_ON_GRAY


def test_pixels_outside_every_mask_are_unchanged():
    out = draw_layers(gray_image(), [layer()])

    assert out.getpixel(OUTSIDE) == (100, 100, 100)


def test_legend_goes_in_a_strip_below_the_image_and_covers_none_of_it():
    out = draw_layers(gray_image(), [layer(top=0, left=0)], alpha=0.5)

    assert out.width == SIZE[0] and out.height > SIZE[1]
    frame = np.asarray(out)[:SIZE[1]]
    assert (frame[~square_mask(top=0, left=0)] == 100).all()  # burned-in text in any corner stays visible
    assert out.getpixel((5, 8)) == RED_ON_GRAY  # where a corner legend used to go


def test_legend_shows_each_layer_color():
    layers = [layer(color=(255, 0, 0), label="plume"), layer(color=(0, 255, 0), label="fountain", top=20, left=20)]

    out = draw_layers(gray_image(), layers)

    strip = np.asarray(out)[SIZE[1]:].reshape(-1, 3)
    assert {(255, 0, 0), (0, 255, 0)} <= {tuple(int(v) for v in pixel) for pixel in strip}


def test_min_legend_rows_give_every_frame_of_a_video_the_same_size():
    two_layers = [layer(), layer(color=(0, 255, 0), top=20, left=20)]

    sizes = {draw_layers(gray_image(), layers, min_legend_rows=2).size for layers in ([], [layer()], two_layers)}

    assert len(sizes) == 1


def test_without_layers_the_image_keeps_its_size():
    assert draw_layers(gray_image(), []).size == SIZE


def test_input_image_is_not_modified():
    image = gray_image()

    draw_layers(image, [layer(color=(0, 255, 0), label="steam")])

    assert image.getpixel(INSIDE) == (100, 100, 100)


def test_mask_with_a_different_shape_than_the_image_is_rejected():
    with pytest.raises(ValueError, match="shape"):
        draw_layers(gray_image(), [layer(shape=(10, 10), top=0, left=0, size=3)])
