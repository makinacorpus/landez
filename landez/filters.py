class Filter(object):
    @property
    def basename(self):
        return self.__class__.__name__

    def process(self, image):
        return image

    @classmethod
    def string2rgba(cls, colorstring):
        """ Convert #RRGGBBAA to an (R, G, B, A) tuple """
        colorstring = colorstring.strip()
        if colorstring[0] == '#':
            colorstring = colorstring[1:]
        if len(colorstring) < 6:
            raise ValueError("input #%s is not in #RRGGBB format" % colorstring)
        r, g, b = colorstring[:2], colorstring[2:4], colorstring[4:6]
        a = 'ff'
        if len(colorstring) > 6:
            a = colorstring[6:8]
        r, g, b, a = [int(n, 16) for n in (r, g, b, a)]
        return (r, g, b, a)


class GrayScale(Filter):
    def process(self, image):
        return image.convert('L')


class ColorToAlpha(Filter):
    def __init__(self, color):
        self.color = color

    @property
    def basename(self):
        return super(ColorToAlpha, self).basename + self.color

    def process(self, image):
        # Code taken from Phatch - Photo Batch Processor
        # Copyright (C) 2007-2010 www.stani.be

        from PIL import Image, ImageMath

        def difference1(source, color):
            """When source is bigger than color"""
            return (source - color) / (255.0 - color)

        def difference2(source, color):
            """When color is bigger than source"""
            return (color - source) / color

        def color_to_alpha(image, color=None):
            image = image.convert('RGBA')

            color = map(float, Filter.string2rgba(self.color))
            img_bands = [band.convert("F") for band in image.split()]

            # Find the maximum difference rate between source and color. I had to use two
            # difference functions because ImageMath.eval only evaluates the expression
            # once.
            alpha = ImageMath.eval(
                """float(
                    max(
                        max(
                            max(
                                difference1(red_band, cred_band),
                                difference1(green_band, cgreen_band)
                            ),
                            difference1(blue_band, cblue_band)
                        ),
                        max(
                            max(
                                difference2(red_band, cred_band),
                                difference2(green_band, cgreen_band)
                            ),
                            difference2(blue_band, cblue_band)
                        )
                    )
                )""",
                difference1=difference1,
                difference2=difference2,
                red_band = img_bands[0],
                green_band = img_bands[1],
                blue_band = img_bands[2],
                cred_band = color[0],
                cgreen_band = color[1],
                cblue_band = color[2]
            )
            # Calculate the new image colors after the removal of the selected color
            new_bands = [
                ImageMath.eval(
                    "convert((image - color) / alpha + color, 'L')",
                    image = img_bands[i],
                    color = color[i],
                    alpha = alpha
                )
                for i in xrange(3)
            ]
            # Add the new alpha band
            new_bands.append(ImageMath.eval(
                "convert(alpha_band * alpha, 'L')",
                alpha = alpha,
                alpha_band = img_bands[3]
            ))
            return Image.merge('RGBA', new_bands)

        return color_to_alpha(image, self.color)
