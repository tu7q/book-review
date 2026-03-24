import os
from pathlib import Path
import argparse
import shutil
import time
from http.server import SimpleHTTPRequestHandler, HTTPServer
import threading
import datetime
import toml

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from jinja2 import Environment, FileSystemLoader

from markdown_it import MarkdownIt
from mdit_py_plugins.front_matter import front_matter_plugin

import yaml

baseUrl = "/"
staticBaseUrl = None


def getBaseUrl():
    return baseUrl


def getStaticBaseUrl():
    if staticBaseUrl is None:
        raise Exception()

    return baseUrl + staticBaseUrl


def getUrl(page):
    return baseUrl + "/".join(page.rel_path.parent.parts)


def getEditUrl(repoUrl, page):
    return repoUrl + "/edit/main/pages/" + str(page.rel_path.parent)


env = Environment(loader=FileSystemLoader("templates"))
env.globals["getBaseUrl"] = getBaseUrl
env.globals["getUrl"] = getUrl
env.globals["getEditUrl"] = getEditUrl
env.globals["getStaticBaseUrl"] = getStaticBaseUrl

md = MarkdownIt("commonmark", {"breaks": True, "html": True}).use(front_matter_plugin)


class Page:
    def __init__(self, rel_path: Path, content: str):
        self.rel_path = rel_path
        tokens = md.parse(content)
        self.content = md.render(content)

        if len(tokens) > 0 and tokens[0].type == "front_matter":
            self.fm = yaml.load(tokens[0].content, Loader=yaml.SafeLoader)
            if "created" in self.fm:
                self.fm["created"] = datetime.datetime.strptime(
                    self.fm["created"], "%d/%m/%Y"
                )
        else:
            self.fm = {}


def get_pages(root):
    pages = []
    for (
        dirpath,
        dirnames,
        filenames,
    ) in os.walk(root):
        rel_dir = Path(*Path(dirpath).parts[1:])

        for filename in filenames:
            if filename == "_index.md":
                rel_path = rel_dir.joinpath("index.html")
            else:
                rel_path = rel_dir.joinpath(filename, "index.html")

            page = Page(rel_path, Path(dirpath, filename).read_text())
            pages.append(page)
    return pages


def build(pages_dir: str, install_dir: str):
    global staticBaseUrl

    install = Path(install_dir)
    pages = get_pages(pages_dir)
    config = toml.load(Path("config.toml"))

    if install.exists():
        shutil.rmtree(install.resolve())
    install.mkdir(parents=False, exist_ok=False)

    if static := config["static"]:
        static_dir = Path(static["src"])
        static_dst = install.joinpath(static["dst"])

        staticBaseUrl = static["dst"]
        # if staticBaseUrl[-1] != "/":
        #     staticBaseUrl += "/"

        shutil.copytree(static_dir, static_dst)

    for page in pages:
        if "template" not in page.fm:
            continue

        template = env.get_template(page.fm["template"])
        rt = template.render(config=config, page=page, pages=pages, **page.fm)

        path = install.joinpath(page.rel_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rt)


class EventHandler(FileSystemEventHandler):
    def __init__(self, s, t, src_dir, install_dir):
        self.source = src_dir
        self.install = install_dir
        self.s = s
        self.t = t

    def on_any_event(self, event: FileSystemEvent) -> None:
        # TODO: Don't respond to every event.

        # Close server. (cleans up temporary files)
        self.s.shutdown()
        self.t.join()

        # Rebuild the website
        try:
            build(self.source, self.install)
        except Exception as _:
            pass

        # Start server.
        self.t = threading.Thread(target=self.s.serve_forever)
        self.t.start()


def watch(source_dir: str, install_dir: str):
    build(source_dir, install_dir)

    server = HTTPServer(
        ("localhost", 8000),
        lambda *_: SimpleHTTPRequestHandler(*_, directory=install_dir),
    )
    t = threading.Thread(target=server.serve_forever)
    t.start()

    handler = EventHandler(server, t, source_dir, install_dir)
    observer = Observer()
    observer.schedule(handler, ".", recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()
        server.shutdown()
        t.join()


def main():
    global baseUrl

    parser = argparse.ArgumentParser(
        prog="Builder",
        description="Builds the static website.",
    )
    subparsers = parser.add_subparsers(required=True)

    # TODO: make this better.
    build_parser = subparsers.add_parser("build")
    build_parser.set_defaults(fn=build)
    build_parser.add_argument("--baseUrl", default="/")
    build_parser.add_argument("-s", "--source", default="pages")
    build_parser.add_argument("-o", "--output", default="web")

    watch_parser = subparsers.add_parser("watch")
    watch_parser.set_defaults(fn=watch)
    watch_parser.add_argument("--baseUrl", default="/")
    watch_parser.add_argument("-s", "--source", default="pages")
    watch_parser.add_argument("-o", "--output", default="web")

    args = parser.parse_args()

    baseUrl = args.baseUrl
    args.fn(args.source, args.output)


if __name__ == "__main__":
    main()
