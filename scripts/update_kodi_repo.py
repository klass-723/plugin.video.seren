"""Update the Kodi repository site (klass-723.github.io) with a new Seren zip.

Usage: update_kodi_repo.py <packages_dir> <new_seren_zip>

Replaces the Seren zip, then regenerates addons.xml, addons.xml.md5 and the
index.html pages from the addon.xml files inside every zip in the packages tree.
"""
import hashlib
import os
import shutil
import sys
import xml.etree.ElementTree as ET
import zipfile


def main(packages_dir, new_seren_zip):
    seren_dir = os.path.join(packages_dir, "plugin.video.seren")
    os.makedirs(seren_dir, exist_ok=True)
    for name in os.listdir(seren_dir):
        if name.endswith(".zip"):
            os.remove(os.path.join(seren_dir, name))
    shutil.copy2(new_seren_zip, os.path.join(seren_dir, os.path.basename(new_seren_zip)))

    addon_xmls = []
    addon_dirs = sorted(
        d for d in os.listdir(packages_dir)
        if os.path.isdir(os.path.join(packages_dir, d))
    )
    for addon_id in addon_dirs:
        addon_dir = os.path.join(packages_dir, addon_id)
        zips = [p for p in os.listdir(addon_dir) if p.endswith(".zip")]
        if not zips:
            continue
        zips.sort(key=lambda p: [int(x) for x in p[:-4].rsplit("-", 1)[1].split(".")])
        with zipfile.ZipFile(os.path.join(addon_dir, zips[-1])) as zf:
            xml_text = zf.read(f"{addon_id}/addon.xml").decode("utf-8")
        addon_xmls.append(xml_text)
        write_index(addon_dir, addon_id, sorted(os.listdir(addon_dir)))

    merged = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<addons>\n'
    for xml_text in addon_xmls:
        merged += xml_text.split("?>", 1)[-1].strip() + "\n"
    merged += "</addons>\n"
    ET.fromstring(merged)

    with open(os.path.join(packages_dir, "addons.xml"), "w") as f:
        f.write(merged)
    md5 = hashlib.md5(merged.encode()).hexdigest()
    with open(os.path.join(packages_dir, "addons.xml.md5"), "w") as f:
        f.write(md5)

    write_index(packages_dir, "Seren Maintained Repository",
                [f"{d}/" for d in addon_dirs] + ["addons.xml", "addons.xml.md5"])
    print(f"Updated {packages_dir}: {len(addon_xmls)} addons, md5 {md5}")


def write_index(directory, title, entries):
    entries = [e for e in entries if e != "index.html"]
    links = "\n".join(f'<li><a href="{e}">{e}</a></li>' for e in entries)
    description = ("Kodi repository for the maintained Seren fork - working Trakt sync and "
                   "Real-Debrid fixes. Add this URL as a file manager source in Kodi.")
    with open(os.path.join(directory, "index.html"), "w") as f:
        f.write(f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
                f'<title>{title}</title><meta name="description" content="{description}"></head>'
                f"<body><h1>{title}</h1><ul>{links}</ul></body></html>\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
