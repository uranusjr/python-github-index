import argparse
import xml.etree.ElementTree as et

import aiohttp
import aiohttp.web


REPOSITORIES = {"sampleproject": ("uranusjr", "sampleproject")}


def _create_session(request, overwrite_headers=None):
    """Create a HTTP client session for API access.
    """
    try:
        auth = request.headers["Authorization"]
    except KeyError:
        headers = overwrite_headers
    else:
        headers = {"Authorization": auth}
        headers.update(overwrite_headers)
    return aiohttp.ClientSession(headers=headers)


def _endpoint(*parts):
    """Build an API endpoint URL from parts.
    """
    s = "/".join(p.strip("/") for p in parts)
    return f"https://api.github.com/{s}"


# Possible distribution extensions.
DIST_EXTS = [".tar.gz", ".whl"]  # Source.  # Wheel.


def _is_dist(asset):
    """Whether a file looks like a Python package distribution.
    """
    if not any(asset["name"].endswith(ext) for ext in DIST_EXTS):
        return False
    if asset["state"] != "uploaded":
        return False
    return True


def _iter_dist_assets(data):
    for release in data:
        for asset in release.get("assets", []):
            if _is_dist(asset):
                yield asset


routes = aiohttp.web.RouteTableDef()


@routes.get("/index/{name}/")
async def project(request):
    """Index page for project of `name`.

    This generates an HTML page compliant to PEP 503 (Simple Repository API)
    for pip to consume.
    """
    try:
        user, repo = REPOSITORIES[request.match_info["name"]]
    except KeyError:
        raise aiohttp.web.HTTPNotFound()

    url = _endpoint("repos", user, repo, "releases")
    async with _create_session(request) as session:
        async with session.get(url) as api_resp:
            if api_resp.status != 200:
                return aiohttp.web.Response(
                    body=(await api_resp.json())["message"],
                    status=api_resp.status,
                )

            body = et.Element("body")
            for asset in _iter_dist_assets(await api_resp.json()):
                url = request.app.router["download"].url_for(
                    user=user,
                    repo=repo,
                    asset_id=str(asset["id"]),
                    filename=asset["name"],
                )
                para = et.SubElement(body, "p")
                anchor = et.SubElement(para, "a", {"href": str(url)})
                anchor.text = asset["name"]
            body = et.tostring(body, encoding="utf-8", method="html")

    return aiohttp.web.Response(
        body=body,
        content_type="text/html",
        charset="utf-8",
    )


CHUNK_SIZE = 1024


@routes.get("/files/{user}/{repo}/{asset_id}/{filename}", name="download")
async def download(request):
    # Reconstruct the URL to read from received parameters.
    url = _endpoint(
        "repos",
        request.match_info["user"],
        request.match_info["repo"],
        "releases/assets",
        request.match_info["asset_id"],
    )

    # Stream-read the URL, and stream write whatever received out.
    headers = {"Accept": "application/octet-stream"}
    async with _create_session(request, headers) as session:
        async with session.get(url) as api_resp:
            # AIOHTTP auto-follows redirects, so the response always has
            # 200 on success, never 302.
            if api_resp.status != 200:
                return aiohttp.web.Response(
                    body=(await api_resp.json())["message"],
                    status=api_resp.status,
                )

            my_resp = aiohttp.web.StreamResponse(headers=api_resp.headers)
            await my_resp.prepare(request)

            while True:
                chunk = await api_resp.content.read(CHUNK_SIZE)
                if not chunk:
                    break
                await my_resp.write(chunk)

    return my_resp


def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port")
    options = parser.parse_args()

    app = aiohttp.web.Application()
    app.add_routes(routes)
    aiohttp.web.run_app(app, port=options.port)


if __name__ == '__main__':
    _main()
