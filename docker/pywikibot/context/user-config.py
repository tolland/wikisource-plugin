family = "mywikisource"
mylang = "en"
usernames["mywikisource"]["en"] = "admin"  # noqa F821
password_file = None
editor: bool | str | None = None
editor_encoding = "utf-8"
editor_filename_extension = "wiki"
log: list[str] = []
logfilename: str | None = None
logfilesize = 1024
logfilecount = 5
verbose_output = 0
log_pywiki_repo_version = False
debug_log: list[str] = []
user_script_paths: list[str] = [
    "/app/scripts",
]

user_families_paths: list[str] = []

upload_to_commons = False
minthrottle = 0.1
maxthrottle = 60
put_throttle: int | float = 3
noisysleep = 3.0
maxlag = 5
step = -1
max_retries = 5
retry_wait = 3
retry_max = 120
socket_timeout = (6.05, 45)
cosmetic_changes = False
cosmetic_changes_mylang_only = True
cosmetic_changes_enable: dict[str, tuple[str, ...]] = {}
cosmetic_changes_disable: dict[str, tuple[str, ...]] = {}
cosmetic_changes_deny_script = [
    "category_redirect",
    "cosmetic_changes",
    "newitem",
    "touch",
]
actions_to_block: list[str] = []
simulate: bool | str = False
max_queue_size = 64
pickle_protocol = 5
interwiki_backlink = True
interwiki_shownew = True
interwiki_graph = False
interwiki_min_subjects = 100
interwiki_graph_formats = ["png"]
interwiki_graph_url = None
without_interwiki = False
sort_ignore_case = False
max_external_links = 50
report_dead_links_on_talk = False
weblink_dead_days = 7
replicate_replace: dict[str, dict[str, str]] = {}
