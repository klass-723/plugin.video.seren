# Seren Maintained Install and Update Guide

This fork is a maintained build of Seren for Kodi based on work by Nixgates, bbviking, and the Seren community. The current build is always the newest zip on the Releases page.

## Before Installing

- Use Kodi 19 or newer.
- Use the release zip named like `plugin.video.seren-<version>.zip`.
- Do not use GitHub's automatic `Source code` zip as the normal Kodi install file.
- Seren still needs a compatible debrid account and a provider package for normal scraping/playback.

## Fresh Install

1. Download the latest `plugin.video.seren-*.zip` from this repo's Releases page.
2. In Kodi, go to `Settings > System > Add-ons`.
3. Enable `Unknown sources` if Kodi asks for it.
4. Go to `Add-ons > Install from zip file`.
5. Select the downloaded Seren zip.
6. Open Seren settings and authorize Trakt if you use Trakt menus.
7. Open `Seren > Tools > Provider Tools > Install Package` to install your provider package.

## Updating From Another Seren Build

Install the new zip over the existing Seren install. Do not uninstall first unless you want to reset everything.

After updating:

1. Restart Kodi.
2. Open Seren once and let background startup finish.
3. If Trakt menus are empty, run `Seren > Tools > Trakt Sync Tools > Force Sync`.
4. If watched/collection data is still wrong, run `Seren > Tools > Trakt Sync Tools > Rebuild Database`.

When Kodi asks whether to remove add-on data during an uninstall, choose `No` unless you intentionally want to erase Seren settings, Trakt auth, provider packages, cache, and local databases.

## Provider Packages

Provider packages are separate from Seren. Updating Seren does not automatically replace or repair a provider package.

To check providers:

1. Open `Seren > Tools > Provider Tools`.
2. Use `Manage Provider Packages` to see installed packages.
3. Use `Check For Updates` if your installed package supports updates.
4. Use `Install Package` if no providers are installed.

## If Something Breaks

Send both logs after reproducing the issue:

- `kodi.log`
- `kodi.old.log`

Also include the exact Seren menu path that failed, for example `My Movies > My Watched Movies` or `Discover TV Shows > New TV Shows`.
