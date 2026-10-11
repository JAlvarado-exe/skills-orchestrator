"""Shared helpers for building synthetic skill trees in tests."""
import os


def write(root, rel, content, newline=""):
    path = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline=newline) as handle:
        handle.write(content)
    return path


def skill(root, rel_dir, name, description, body="Body.\n", extra=""):
    text = "---\nname: %s\ndescription: %s\n%s---\n\n%s" % (name, description, extra, body)
    return write(root, rel_dir + "/SKILL.md", text)
