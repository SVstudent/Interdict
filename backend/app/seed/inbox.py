"""The business office inbox.

Twenty-five messages of the kind a school district business manager actually gets in a morning.
Most are ordinary: invoices, delivery questions, a W-9, a purchase order query, somebody chasing a
late payment. Three of them are attempts to move money.

That ratio is the point. The fleet is not impressive because it can analyse one obviously
suspicious email — it is impressive because it reads the whole morning's post, decides on its own
which three deserve an investigation, and leaves the other twenty-two alone.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass
class InboxMessage:
    message_id: str
    received_at: datetime
    sender_name: str
    sender_email: str
    subject: str
    body: str
    has_attachment: bool = False
    attachment_name: str | None = None
    # Set when this message is the trigger for one of the demo scenarios.
    scenario_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "received_at": self.received_at.isoformat(),
            "sender_name": self.sender_name,
            "sender_email": self.sender_email,
            "subject": self.subject,
            "body": self.body,
            "has_attachment": self.has_attachment,
            "attachment_name": self.attachment_name,
            "scenario_id": self.scenario_id,
        }


# (minutes_ago, sender, email, subject, body, attachment)
ORDINARY: list[tuple[int, str, str, str, str, str | None]] = [
    (12, "Dana Whitfield", "d.whitfield@brightmoor-facilities.test",
     "Invoice INV-7742 — September custodial",
     "Morning — attaching September's custodial invoice. Same scope as August, no change to the "
     "hours. Let me know if you need the site breakdown again.", "INV-7742.pdf"),
    (24, "Marcus Oyelaran", "m.oyelaran@calder-food.test",
     "Delivery window change — Lincoln Elementary",
     "Heads up that Thursday deliveries to Lincoln are moving to 6:30am starting next week. "
     "Nothing needed from you, just so the kitchen staff aren't surprised.", None),
    (31, "Priya Raman", "p.raman@vantage-print.test",
     "Re: PO 4471 — quantity query",
     "You ordered 400 report card stock but the PO says 4000. I've held the run until you "
     "confirm which is right — didn't want to print ten times what you need.", None),
    (38, "Terrance Blake", "t.blake@selkirk-bus.test",
     "Bus 14 brake inspection — scheduling",
     "Bus 14 is due its brake inspection. I can take it Tuesday or Thursday, whichever leaves "
     "you better covered for the afternoon routes.", None),
    (45, "Ellen Marsh", "e.marsh@alderwood-books.test",
     "Backorder: 6th grade literature set",
     "The Hatchet class set is backordered until the 19th. I can substitute the newer edition "
     "at the same price if you'd rather not wait.", None),
    (52, "Hugo Fenwick", "h.fenwick@fenwick-lab.test",
     "Annual calibration due — chemistry lab",
     "Your fume hood calibration lapses at the end of the month. Want me to book the usual "
     "slot?", None),
    (58, "Rosa Delgado", "accounts@lowry-custodial.test",
     "Statement of account — August",
     "Attaching August's statement. Everything is settled apart from INV-6610, which I think "
     "crossed with your payment run.", "STMT-AUG.pdf"),
    (63, "Iain Thornbury", "i.thornbury@thornbury-window.test",
     "Gym window replacement — access on the 14th",
     "We'll need the gym clear from 7am on the 14th. Two days, weather permitting.", None),
    (71, "Nadia Kaur", "n.kaur@garrick-safety.test",
     "Bloodborne pathogen training — headcount",
     "Do you want the same 40 seats as last year, or should I add the new paraprofessionals?", None),
    (78, "Owen Castellanos", "o.castellanos@merrow-electrical.test",
     "Quote: auditorium lighting circuit",
     "Attaching the quote for the auditorium circuit work. It's about 8% over the estimate "
     "because of the conduit run — happy to walk through it.", "QUOTE-2214.pdf"),
    (84, "Bethany Lowe", "b.lowe@quarry-lane.test",
     "Parking lot resurfacing — start date",
     "Can we start the north lot on the 21st? Needs five dry days.", None),
    (91, "Samuel Achebe", "s.achebe@pemberton-play.test",
     "Playground inspection report",
     "Attaching the annual inspection. Two items on the Whitmore structure need attention but "
     "nothing that closes it.", "INSPECT-2026.pdf"),
    (99, "Grace Lindqvist", "g.lindqvist@redgate-sis.test",
     "SIS maintenance window — Sunday 2am",
     "Routine maintenance Sunday 2-5am. No action needed.", None),
    (106, "Victor Amadi", "v.amadi@halloway-uniform.test",
     "Track uniforms — size exchange",
     "The mediums came in short. I'm sending replacements, no charge, no paperwork needed on "
     "your end.", None),
    (114, "Joanne Pryce", "j.pryce@ironbridge-roofing.test",
     "Roof section C — progress photos",
     "Attaching this week's photos. On schedule.", "PHOTOS-WK3.pdf"),
    (121, "Elias Mbeki", "e.mbeki@culver-driver.test",
     "Two more CDL candidates ready for road test",
     "Both cleared the written. Can you get them on the schedule?", None),
    (129, "Anneke Visser", "a.visser@padstow-sped.test",
     "Re: service minutes — quarterly reconciliation",
     "Our minutes and yours differ by about four hours for July. I've attached our log so we "
     "can find where it drifted.", "LOG-JUL.pdf"),
    (136, "Curtis Rowan", "c.rowan@kestrel-athletic.test",
     "Wrestling mats — delivery confirmation",
     "Mats delivered and signed for at the middle school this morning.", None),
    (144, "Yuki Tanaka", "y.tanaka@ashfield-science.test",
     "Chemical inventory — disposal pickup",
     "Disposal pickup is booked for the 12th. Please have the cabinet inventory ready.", None),
    (151, "Desmond Frye", "d.frye@northwind-transport.test",
     "Route 7 — substitute driver next week",
     "Ana's out next week so Route 7 will have a sub. Same times.", None),
    (159, "Maria Okonjo", "m.okonjo@brightmoor-facilities.test",
     "Supply closet key — Jefferson",
     "The custodial closet at Jefferson has a sticking lock. Can facilities take a look?", None),
    (168, "Trevor Nsimba", "t.nsimba@calder-food.test",
     "Free/reduced enrollment numbers",
     "Do you have the updated counts? I need them to adjust next month's order.", None),
]


def build_inbox(now: datetime, scenario_requests: dict[str, Any] | None = None) -> list[InboxMessage]:
    """The morning's post, newest first.

    Scenario messages are interleaved among the ordinary ones rather than placed at the top —
    if the attacks sat conveniently at the front, the triage would not be demonstrating anything.
    """
    messages = [
        InboxMessage(
            message_id=f"MSG-{4000 + i}",
            received_at=now - timedelta(minutes=mins),
            sender_name=name,
            sender_email=email,
            subject=subject,
            body=body,
            has_attachment=attachment is not None,
            attachment_name=attachment,
        )
        for i, (mins, name, email, subject, body, attachment) in enumerate(ORDINARY)
    ]

    for scenario_id, minutes, subject in (
        ("S1", 7, "Updated remittance details — invoice INV-4471"),
        ("S2", 67, "Remittance update (see attached) — INV-5120"),
        ("S3", 133, "Remittance update following group acquisition — INV-6204"),
    ):
        messages.append(InboxMessage(
            message_id=f"MSG-{scenario_id}",
            received_at=now - timedelta(minutes=minutes),
            sender_name="—",
            sender_email="—",
            subject=subject,
            body="",          # filled from the scenario fixture at read time
            scenario_id=scenario_id,
        ))

    return sorted(messages, key=lambda m: m.received_at, reverse=True)
