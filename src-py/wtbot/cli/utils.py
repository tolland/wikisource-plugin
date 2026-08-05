from wtbot.settings import WikiSettings


def _settings(
    family: str, code: str, api_url: str | None, ca_bundle: str | None
) -> WikiSettings:
    return WikiSettings(family=family, code=code, api_url=api_url, ca_bundle=ca_bundle)
