# NexusAI landing page

A static page with no build step. `deploy.py` puts it on the Linux update server, next to the update feed, and points its Download button at an installer already in the feed.

| File | What it is |
|---|---|
| `index.html` | The page: styles, content and scripts |
| `fonts/` | Bundled fonts, so the page calls nothing outside your server |
| `release.js` | Installer details. This copy is for local preview; `deploy.py` writes the real one on the server |
| `deploy.py` | The deploy command. Needs only Python 3.8 or newer |
| `deploy.example.json` | Config template. Copy it to `deploy.json`, which Git ignores, so internal addresses stay out of the repo |

To preview it, open `index.html` in a browser. The Download button only works once deployed.

The GitHub, Features and Known problems links are placeholders that go nowhere, and nothing deployed contains a GitHub address. To make one work, give it an `href` in `index.html`.

## How the pieces fit

```text
Windows build machine                 Linux server (/srv/nexusai-updates)
desktop.cmd release  ── uploads ──▶   windows/x64/unsigned/0.1.0/NexusAI-Beta-Setup-0.1.0.exe
                                      windows/x64/unsigned/0.1.0/release.json
                                      windows/x64/unsigned/pilot.yml

website/deploy.py    ── writes ───▶   index.html, release.js, fonts/
```

Nginx serves all of it from the one site on port 8088. There's only one copy of each installer: the page links to the same file the app's updater uses. `deploy.py` never writes under `windows/`, so it can't disturb updates.

## First deploy

Do this on the Linux server, as the user that owns `/srv/nexusai-updates`. `desktop.cmd server-setup` must have run already, and at least one release must be published.

```sh
git clone https://github.com/maheshyadav007/nexusai.git
cd nexusai
cp website/deploy.example.json website/deploy.json
nano website/deploy.json                  # set publicUrl
python3 website/deploy.py --check         # shows what it found, changes nothing
python3 website/deploy.py --setup-nginx   # once only, asks for your sudo password
```

`--setup-nginx` reruns `desktop/linux/setup.sh`, which now also serves the page. Update checks use the same site and keep working. It's only needed once on each server.

## Each new release

1. On the Windows build machine, run `desktop.cmd release` as usual.
2. On the Linux server, run:

```sh
python3 website/deploy.py
```

With `version` set to `latest`, the deploy finds the newest version by itself, from the channel file the release tool updates. It only looks when it runs, so to pick up new releases without you, add this with `crontab -e`, using your own path:

```text
*/15 * * * * cd /home/you/nexusai && python3 website/deploy.py >> /tmp/nexusai-site.log 2>&1
```

## Changing the page

Pull the change on the server, then run `python3 website/deploy.py`. Visitors get it on their next page load.

Fonts are cached for a year because their names don't change. If you replace a font, give the file a new name and update it in `index.html`.

## Config: `website/deploy.json`

| Setting | Meaning | Example |
|---|---|---|
| `version` | `latest` finds the newest published version in the feed. Set a number, like `0.1.0`, to hold the page on that version | `latest` |
| `channel` | Channel file `latest` reads: `pilot` or `latest`. Unsigned builds publish to `pilot`, signed stable builds to `latest`. Ignored when `version` is a number | `pilot` |
| `releaseRoot` | The folder Nginx serves. Same as `server.root` in `.release/profile/release.json` | `/srv/nexusai-updates` |
| `installerFolder` | Where version folders live, relative to `releaseRoot`. Unsigned builds use `windows/x64/unsigned`, signed builds `windows/x64` | `windows/x64/unsigned` |
| `port` | Nginx port. Same as `server.port` | `8088` |
| `publicUrl` | The address people open. The deploy checks the live page through it | `http://nexus-host:8088` |
| `tlsCertificate`, `tlsKey` | Server paths to the certificate and key, for HTTPS. Must match `server.tlsCertificate` and `server.tlsKey`, because `--setup-nginx` rewrites the site. Blank for HTTP | |

The installer's name, size and checksum aren't in the config. They come from the version's `release.json`, and the file on disk is checked against it.

## What a deploy checks

It stops before changing anything if the version folder or installer is missing, or the checksum doesn't match. After writing, it requests the page, `release.js` and the installer through `publicUrl`, and fails if a visitor wouldn't get the right ones. Rerunning it is safe.

| Message | What to do |
|---|---|
| `deploy.json not found` | Copy `deploy.example.json` to it |
| `Version X isn't in ...` | Publish that version from Windows, or fix `version` |
| `doesn't match its checksum` | The upload is damaged. Publish it again with a new version |
| `The Nginx config doesn't serve the page yet` | Run with `--setup-nginx` |
| `Can't write to ...` | Run as the folder's owner, without `sudo` |
| `Couldn't reach ...` | Check `publicUrl`, that Nginx is running, and the firewall |

## Undeploying

Delete `index.html`, `release.js` and `fonts/` from `releaseRoot`. The root address returns 404 again, and updates aren't affected.
