import pywikibot
import sqlalchemy
from pywikibot.proofreadpage import ProofreadPage
from sqlalchemy import text

## get the page at issue here

page_title = (
    "Page:The_principles_of_mechanics_presented_in_a_new_form_(Hertz,_1894).pdf/40"
)

site_local = pywikibot.Site("local", "mywikisource")

page_local = ProofreadPage(site_local, page_title)

print(f"{page_local.title()=}")
print(f"{page_local.pageid=}")
for rev in page_local.revisions():
    print(f"{rev.revid=}")
    for key, slot in rev.slots.items():
        print(f"{key=}")

engine = sqlalchemy.create_engine(
    "mariadb+mariadbconnector://mediawiki:mediawiki@172.16.6.3:3306/mediawiki"
)

with engine.connect() as conn:
    result = conn.execute(text("""
                               SELECT p.*, r.*
                               FROM page p
                                        INNER JOIN revision r ON p.page_id = r.rev_page
                                        INNER JOIN slots s ON r.rev_id = s.slot_revision_id
                                        INNER JOIN content c ON s.slot_content_id = c.content_id
                               WHERE p.page_title = REPLACE('The principles of mechanics presented in a new form (Hertz, 1894).pdf/40', ' ', '_');
                               """))
    print(result.all())

    result2 = conn.execute(text("""
                               SELECT p.*, r.*
                               FROM page p
                                        INNER JOIN revision r ON p.page_id = r.rev_page
                                        INNER JOIN slots s ON r.rev_id = s.slot_revision_id
                                        INNER JOIN content c ON s.slot_content_id = c.content_id
                               WHERE r.rev_id = 232;
                               """))
    print(result2.all())
