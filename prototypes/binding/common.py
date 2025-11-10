class WidgetRef:
    def __init__(self, name: str, widget):
        self.name = name
        self.widget = widget
    def __str__(self):
        return self.name
