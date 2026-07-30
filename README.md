[![Kodi version](https://img.shields.io/badge/kodi%20versions-19--21-blue)](https://kodi.tv/)
[![CI](https://github.com/klass-723/plugin.video.seren/actions/workflows/ci.yml/badge.svg)](https://github.com/klass-723/plugin.video.seren/actions)
[![Latest release](https://img.shields.io/github/v/release/klass-723/plugin.video.seren)](https://github.com/klass-723/plugin.video.seren/releases)
[![License: GPL3](https://img.shields.io/badge/License-GPL3-yellow.svg)](https://opensource.org/licenses/GPL-3.0)

# Seren (plugin.video.seren) — maintained, Trakt working again

**Seren is alive.** This maintained fork fixes the June 2026 Trakt API changes that broke sync, Next Up, watched history, and lists in every older Seren build ([details](https://github.com/trakt/trakt-api/discussions/775)) — plus the earlier Real-Debrid playback fixes, pagination, calendar, and menu fixes throughout, with an auto-updating install repository.

The original Seren add-on was created by Nixgates; this fork is based on bbviking's 3.0.x maintenance work, with MrSpongeHead's `extended=progress` finding carried in.

## Problems this fork fixes

- Trakt asks to re-authorize, then the sync or database rebuild finishes in a second with no data
- Next Up is empty or errors, watched history and My Shows/My Movies menus are blank
- Trakt personal lists and liked lists don't load
- Real-Debrid playback failures on cached and uncached torrents (the 2026 RD fixes from bbviking's line are included)
- Provider package installs silently corrupting with `ModuleNotFoundError` (Seren zip extractor bug, fixed here in 3.0.69)

Seren is a multi-source addon for Kodi with the added ability to install custom provider modules. Unlike other Kodi addons which are generally built for a single service use, Seren allows users to connect to multiple online/offline services at once for their viewing with a single click.

## Install and Update

Quick install with automatic updates: add `https://klass-723.github.io/packages/` as a file manager source in Kodi, install `repository.seren.maintained-1.0.0.zip` from it, then install Seren from the repository.

Full instructions, including manual zip installs, are in [INSTALL.md](INSTALL.md).

## Credits

- Nixgates created the original Seren add-on.
- bbviking maintained the 3.0.x fork this build is based on, including the Real-Debrid fixes and selected maintenance work carried into `3.0.66`.
- Community Seren forks and testers, including MrSpongeHead's fork, helped identify Trakt compatibility issues reviewed while preparing this build.
- [a4kScrapers](https://github.com/a4k-openproject/a4kScrapers) is the recommended provider package (see [INSTALL.md](INSTALL.md)); [minhgi's extended scraper pack](https://github.com/minhgi/repository.seren-scrapers) is a community option whose packaging also surfaced the zip extractor bug fixed in `3.0.69`.

## Contribution

Install all dependencies in requirements.txt
```shell
pip install -r requirements.txt
```

Configure hooks for automated pre commit changes:
```sh
pre-commit install
```
Ensure that `git` is available in your PATH

## FAQ

> #### How do I install a new provider?

In the settings menu of Seren you will find a providers tab. Inside this tab you will find the install provider package option.

> #### How do manage my providers?

Within Seren's settings, you will find the providers tab. Within this tab you can disable/enable single providers inside provide packs, enable/disable entire provider packages, enable/ disable automatic provider updates and manually for a update check for your providers.

> #### Seren won't show me season or episode lists and instead begins playing automatically?

Please disable the Auto Episode Resume setting in the general tab of Seren's settings.

> #### I'm experiencing an issue whilst using Seren. Where can I get help?
You can often find help from users in the Addons4Kodi subreddit or you are always welcome to log a github issue and I will contact you directly to investigate the issue.

## License

Licensed under The GPL License.


## [![Repography logo](https://images.repography.com/logo.svg)](https://repography.com) Recent activity [![Time period](https://images.repography.com/31557107/SerenKodi/SerenDevelopment/recent-activity/54b09eb47a7d1f063e1adf376fe18f03_badge.svg)](https://repography.com)
[![Timeline graph](https://images.repography.com/31557107/SerenKodi/SerenDevelopment/recent-activity/54b09eb47a7d1f063e1adf376fe18f03_timeline.svg)](https://github.com/SerenKodi/SerenDevelopment/commits)
[![Issue status graph](https://images.repography.com/31557107/SerenKodi/SerenDevelopment/recent-activity/54b09eb47a7d1f063e1adf376fe18f03_issues.svg)](https://github.com/SerenKodi/SerenDevelopment/issues)
[![Pull request status graph](https://images.repography.com/31557107/SerenKodi/SerenDevelopment/recent-activity/54b09eb47a7d1f063e1adf376fe18f03_prs.svg)](https://github.com/SerenKodi/SerenDevelopment/pulls)
[![Trending topics](https://images.repography.com/31557107/SerenKodi/SerenDevelopment/recent-activity/54b09eb47a7d1f063e1adf376fe18f03_words.svg)](https://github.com/SerenKodi/SerenDevelopment/commits)
