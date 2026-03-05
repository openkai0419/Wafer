from afterimages.plugin import ImageViewerPlugin as _ImageViewerPlugin


class ImageViewerPlugin(_ImageViewerPlugin):
    NAME = 'image'
    EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
    PRIORITY = 100

    def load_content(self, path: str):
        return None
