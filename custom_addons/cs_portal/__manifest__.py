# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

{
    "name": "Client Services Portal",
    "summary": """Client Services Portal""",
    "version": "1.0.0",
    "sequence": -100,
    "license": "AGPL-3",
    "category": "Productivity",
    "author": "Alvin Dumpit",
    "website": "",
    "depends": ["base", "mail"],
    "data": [
        "data/cs_portal_data.xml",
        # "data/cs_portal_pipeline_data.xml",
        "security/cs_portal_security.xml",
        "security/ir.model.access.csv",
        "views/actions.xml",
        "views/menu.xml",
        "views/views.xml",

    ],
    "development_status": "Beta",
    "application": True,
    "installable": True,
}