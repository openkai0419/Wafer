from .commandbase import CommandMeta, CommandParam, RegistryBackedMenu
from datetime import datetime


class FileMenu(RegistryBackedMenu):
    path_prefix = "file"
    def create_definitions(self):
        items = [":File"]
        for i in range(4):
            items.append({
                "path": f"file.{i}",
                "meta": CommandMeta(display=f"file {i}"),
                "func": (lambda x=i: (lambda: print(f"file {x}")))(),
            })
        return items


class PathMenu(RegistryBackedMenu):
    path_prefix = "path"
    def create_definitions(self):
        items = [":Path", "-"]
        for i in range(4):
            items.append({
                "path": f"path.{i}",
                "meta": CommandMeta(display=f"path {i}"),
                "func": (lambda x=i: (lambda: print(f"path {x}")))(),
            })
        i = 3
        items.append({
            "path": f"Temp/path.Test{i}",
            "meta": CommandMeta(display=f"Temp {i}"),
            "func": (lambda x=i: (lambda: print(f"path {x}")))(),
        })
        return items


class CmdMenu(RegistryBackedMenu):
    path_prefix = "commands"
    def create_definitions(self):
        return [
            ":Commands",
            {"path": "hello", "meta": CommandMeta(display="Hello", params=[CommandParam(name="widget", type=str, default="", description="Widget")]), "func": lambda widget="": print(f"hello from {widget}")},
            {"path": "time", "meta": CommandMeta(display="Show Time"), "func": lambda: print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))},
            "-",
            ":Options",
            {"path": "Options/echo", "meta": CommandMeta(display="Echo", params=[CommandParam(name="text", type=str, default="echo")], has_options=True), "func": lambda text="echo": print(text)},
            {"path": "Options/count", "meta": CommandMeta(display="Count", params=[CommandParam(name="value", type=int, default=1, description="Value")], has_options=True), "func": lambda value=1: print(f"count {value}")},
            "-",
            ":Toggle",
            {"path": "Toggle/toggleVerbose", "meta": CommandMeta(display="Verbose Mode", checkable=True, default_checked=False, params=[CommandParam(name="checked", type=bool, default=False)]), "func": lambda checked=False: print("verbose on" if checked else "verbose off")},
        ]
