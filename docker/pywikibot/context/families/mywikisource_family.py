from pywikibot import family


class Family(family.Family):  # noqa: D101

    name = "mywikisource"

    langs = {
        "en": "localhost:8080",
    }

    def scriptpath(self, code):
        return {
            "en": "/w",
        }[code]

    def protocol(self, code):
        return {
            "en": "http",
        }[code]
