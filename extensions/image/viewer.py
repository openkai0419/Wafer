from afterimages.plugin import BaseViewerPlugin


class ImageViewerPlugin(BaseViewerPlugin):
    NAME = 'image'
    EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
    PRIORITY = 100

    def load_content(self, path: str):
        return None
