"""A made-up mailbox of a senior engineer at a large R&D company, with what each email really is.

Written before the grouping engine and kept apart from it: the engine never reads this file, and a
test checks that none of its senders, tags or names appear in the engine. It holds cases the engine
may get wrong on purpose, such as a tool that sends through Exchange like a person, a tracker whose
subjects change per issue, a wiki whose subjects never repeat, and colleagues who send the same
weekly subject. Everything is seeded, so the same 1,000 emails come out every time.

Each label says what the email is, never which folder to use:
- truth: the group it belongs to, such as "plm" or "hr"
- machine: sent by a tool or a bulk mailer rather than written by a person
- calendar: carries a calendar invitation or response (a text/calendar part or Outlook's mark)
- important: the person would want the AI to see it
"""

import base64
import json
import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

COMPANY = "korvia.example"
OWNER = ("Asha Rao", f"asha.rao@{COMPANY}")
START = datetime(2026, 5, 4, 3, 30, tzinfo=UTC)
DAYS = 196

PEOPLE = [
    ("Vikram Iyer", "Senior Engineer, Camera HAL"),
    ("Min-jun Park", "VP, Mobile Platform R&D"),
    ("Priya Nair", "Engineering Manager, Multimedia"),
    ("Seo-yeon Kim", "Principal Engineer, HQ Suwon"),
    ("Rahul Menon", "Staff Engineer, Kernel"),
    ("Ananya Gupta", "Engineer, Camera HAL"),
    ("Ji-ho Lee", "Project Lead, Modem SW"),
    ("Karthik Subramanian", "Senior Engineer, Power"),
    ("Deepa Krishnan", "Program Manager"),
    ("Hyun-woo Choi", "Senior Engineer, HQ Suwon"),
    ("Sneha Reddy", "Engineer, Multimedia"),
    ("Arjun Bhat", "Test Lead, QA"),
    ("Meera Pillai", "Architect, AI Platform"),
    ("Dong-hyun Jung", "Director, HQ Suwon"),
    ("Nikhil Joshi", "Engineer, Kernel"),
    ("Kavya Shetty", "Engineer, Power"),
    ("Sanjay Kulkarni", "Senior Manager, Camera"),
    ("Eun-ji Yoon", "Engineer, HQ Suwon"),
    ("Rohan Desai", "Engineer, Build & Release"),
    ("Lakshmi Varma", "Engineer, Security"),
]
TEAM = [name for name, _ in PEOPLE] + [
    "Aditya Rao", "Pooja Hegde", "Suresh Babu", "Neha Sharma", "Varun Kapoor",
]  # fmt: skip
TEAMS = ["Camera HAL", "Multimedia", "Kernel", "Power", "Modem SW", "AI Platform"]
PROJECTS = ["Orion", "Vega", "Lyra"]
LISTS = {
    "all": f"all-blr-rnd@{COMPANY}",
    "senior": f"senior-staff-blr@{COMPANY}",
    "camera": f"camera-platform@{COMPANY}",
}


@dataclass
class Label:
    file: str
    truth: str
    machine: bool
    calendar: bool
    important: bool


def address(name: str) -> str:
    return f"{name.lower().replace(' ', '.').replace('-', '')}@{COMPANY}"


def signature(name: str, title: str) -> str:
    return f"Regards,\n{name}\n{title}\nKorvia R&D, Bangalore"


class Mailbox:
    def __init__(self, seed: int, marks: bool = True) -> None:
        self.random = random.Random(seed)
        # A plain server, or mail read through one, carries none of Outlook's marks.
        self.marks = marks
        self.items: list[tuple[EmailMessage, Label]] = []

    # Building blocks

    def when(self) -> datetime:
        moment = START + timedelta(days=self.random.randrange(DAYS))
        return moment.replace(hour=self.random.randrange(2, 15), minute=self.random.randrange(60))

    def thread_index(self, parent: EmailMessage | None) -> str:
        """Outlook marks a conversation with 22 shared bytes, then 5 more per reply."""
        if parent is not None and parent["Thread-Index"]:
            root = base64.b64decode(str(parent["Thread-Index"]))
            return base64.b64encode(root + self.random.randbytes(5)).decode()
        return base64.b64encode(self.random.randbytes(22)).decode()

    def build(
        self,
        sender: tuple[str, str],
        to: list[str],
        subject: str,
        body: str,
        when: datetime,
        *,
        cc: list[str] | None = None,
        outlook: bool = False,
        parent: EmailMessage | None = None,
        headers: dict[str, str] | None = None,
        calendar: str | None = None,
    ) -> EmailMessage:
        message = EmailMessage()
        name, mail = sender
        message["From"] = f"{name} <{mail}>" if name else mail
        message["To"] = ", ".join(to)
        if cc:
            message["Cc"] = ", ".join(cc)
        message["Subject"] = subject
        message["Date"] = format_datetime(when)
        message["Message-ID"] = make_msgid(domain=mail.split("@")[1])
        if parent is not None:
            message["In-Reply-To"] = str(parent["Message-ID"])
            message["References"] = " ".join(
                part
                for part in (str(parent["References"] or ""), str(parent["Message-ID"]))
                if part
            )
        if outlook and self.marks:
            message["Thread-Index"] = self.thread_index(parent)
            message["Thread-Topic"] = subject.split(": ", 1)[-1] if parent is not None else subject
            message["X-MS-Has-Attach"] = ""
            message["X-MS-TNEF-Correlator"] = ""
            message["Content-Language"] = "en-US"
            message["X-MS-Exchange-Organization-AuthAs"] = "Internal"
        message.set_content(body)
        if calendar:
            message.add_attachment(
                calendar.encode(), maintype="text", subtype="calendar", filename="invite.ics"
            )
        # Last, because setting the body drops Content-* headers such as Outlook's Content-Class.
        for key, value in (headers or {}).items():
            message[key] = value
        return message

    def add(self, message: EmailMessage, truth: str, machine: bool, important: bool = False,
            calendar: bool = False) -> EmailMessage:  # fmt: skip
        self.items.append((message, Label("", truth, machine, calendar, important)))
        return message

    def person(self) -> tuple[str, str]:
        return self.random.choice(PEOPLE)

    def pick(self, options: list[str]) -> str:
        return self.random.choice(options)

    # Tools

    def plm(self, count: int, assigned: int) -> None:
        senders = [("PLM Notifier", f"plm-notify@{COMPANY}"), ("", f"plm-prod2@{COMPANY}")]
        footer = "This is an automatically generated message from PLM. Please do not reply."
        for index in range(count + assigned):
            mine = index < assigned
            sender = senders[0] if self.random.random() < 0.7 else senders[1]
            eco, part = self.random.randrange(40000, 49999), self.random.randrange(1000, 9999)
            kind = self.random.randrange(3) if not mine else 2
            owner = OWNER[0] if mine else self.pick(TEAM)
            if kind == 0:
                subject = f"[PLM] ECO-{eco} released to production"
                body = f"ECO: ECO-{eco}\nProject: {self.pick(PROJECTS)}\nOriginator: {owner}\nState: Released\n"
            elif kind == 1:
                state = self.pick(["Approved", "In Review", "Obsolete", "Released"])
                subject = f"[PLM] Part {part}-{self.pick('ABC')} status changed to {state}"
                body = f"Part: {part}\nNew state: {state}\nChanged by: {owner}\n"
            else:
                subject = f"[PLM] Workflow task CR-{eco % 9000} is due"
                body = f"Change request: CR-{eco % 9000}\nAssignee: {owner}\nDue: {self.when():%d %b %Y}\n"
            if self.random.random() < 0.6:
                body += f"\n{footer}"
            message = self.build(sender, [OWNER[1]], subject, body, self.when(),
                                 headers={"X-Mailer": "PLM Notification Service 7.3"})  # fmt: skip
            self.add(message, "plm", True, important=mine)

    def swarm(self, count: int, assigned: int) -> None:
        for index in range(count + assigned):
            mine = index < assigned
            review = self.random.randrange(550000, 560000)
            author = self.pick(TEAM)
            kind = self.random.randrange(3) if not mine else 3
            if kind == 0:
                subject, body = (
                    f"[Swarm] Review {review} updated",
                    f"{author} updated review {review}.\nFiles changed: {self.random.randrange(1, 30)}",
                )
            elif kind == 1:
                subject, body = (
                    f"[Swarm] Change {review}: new comment",
                    f'{author} commented on change {review}:\n"Please rebase on main."',
                )
            elif kind == 2:
                subject, body = (
                    f"[Swarm] Review {review} approved",
                    f"Review {review} was approved by {author}.",
                )
            else:
                subject = f"[Swarm] Review {review}: you were added as a reviewer"
                body = f"{author} added {OWNER[0]} ({OWNER[1].split('@')[0]}) as a reviewer on review {review}.\nPlease review by end of week."
            body += f"\n\nhttps://swarm.{COMPANY}/reviews/{review}"
            self.add(self.build(("Swarm", f"swarm@{COMPANY}"), [OWNER[1]], subject, body, self.when()),
                     "swarm", True, important=mine)  # fmt: skip

    def ro_bot(self, count: int, broken: int) -> None:
        footer = "-- \nThis mail was automatically generated by the RO build system."
        for index in range(count + broken):
            mine = index < broken
            build = self.random.randrange(4000, 4999)
            if mine:
                subject = f"[Orion][Build] {build} failed on main"
                body = f"Build {build} failed.\nSuspect commit by {OWNER[0]}: fix camera timestamp drift\nLog: https://ci.{COMPANY}/{build}"
            else:
                project = self.pick(PROJECTS)
                subject = self.pick([
                    f"[{project}][RO Update] Build {build} passed",
                    f"[{project}][RO Update] Nightly {self.when():%Y-%m-%d} ready",
                    f"[{project}][Build] {build} failed on main",
                ])  # fmt: skip
                body = f"{subject.split('] ')[-1]}\nTriggered by: {self.pick(TEAM)}"
            to = [LISTS["camera"]] if not mine else [OWNER[1]]
            self.add(self.build(("RO Bot", f"ro-bot@{COMPANY}"), to, subject, f"{body}\n\n{footer}", self.when()),
                     "ro-bot", True, important=mine)  # fmt: skip

    def qc(self, count: int, assigned: int, replies: int) -> None:
        """Sent through Exchange, so it carries Outlook's marks like a person's mail does."""
        footer = "Please do not reply to this email. Update the case in the QC portal."
        cases: list[EmailMessage] = []
        for index in range(count + assigned):
            mine = index < assigned
            case = self.random.randrange(20000, 21999)
            if mine:
                subject = f"QC Case #{case} assigned to {OWNER[0]}"
                body = f"Case #{case} is now assigned to {OWNER[0]}.\nSeverity: {self.pick(['Major', 'Critical'])}"
            else:
                subject = self.pick([f"QC Case #{case} assigned to {self.pick(TEAMS)}",
                                     f"QC Case #{case} moved to {self.pick(['Verify', 'Analysis', 'Fix'])}",
                                     f"QC Case #{case} closed"])  # fmt: skip
                body = f"Case #{case}\nReporter: {self.pick(TEAM)}\nModel: SM-{self.random.randrange(900, 999)}X"
            message = self.build(("QC System", f"qc-system@{COMPANY}"), [OWNER[1]], subject,
                                 f"{body}\n\n{footer}", self.when(), outlook=True)  # fmt: skip
            cases.append(self.add(message, "qc", True, important=mine))
        for parent in self.random.sample(cases[assigned:], replies):
            name, title = self.person()
            body = (f"Asha, this looks like the timestamp issue from last month. Can you check the "
                    f"HAL logs and confirm by Thursday?\n\n{signature(name, title)}\n\n"
                    f"-----Original Message-----\nFrom: QC System\n{parent.get_content()}")  # fmt: skip
            reply = self.build((name, address(name)), [OWNER[1]], f"RE: {parent['Subject']}", body,
                               self.when(), outlook=True, parent=parent)  # fmt: skip
            self.add(reply, "colleague-in-tool-thread", False, important=True)

    def ci(self, count: int) -> None:
        for _ in range(count):
            job = self.pick(["orion-camera-unit", "vega-kernel-smoke", "lyra-power-regression"])
            run = self.random.randrange(1000, 3000)
            status = self.pick(["SUCCESS", "FAILURE", "UNSTABLE", "SUCCESS"])
            message = self.build(("Jenkins", f"ci-jenkins@{COMPANY}"), [LISTS["camera"]],
                                 f"[CI] {job} #{run} {status}", f"Build {job} #{run}: {status}\nhttps://ci.{COMPANY}/job/{job}/{run}",
                                 self.when(), headers={"Auto-Submitted": "auto-generated", "X-Jenkins-Job": job})  # fmt: skip
            self.add(message, "ci", True)

    def tracker(self, count: int, assigned: int) -> None:
        """Each issue has its own subject; updates thread onto the first mail, like Jira does."""
        titles = ["Camera preview freezes after HDR toggle", "Kernel panic in suspend path",
                  "Power regression on idle screen", "Modem drops after handover",
                  "Thermal throttling too aggressive", "AI scene detection misses low light",
                  "Build fails with new toolchain", "Crash in gallery thumbnail cache",
                  "Audio glitch during video call", "Battery stats wrong after reboot",
                  "Slow boot on debug builds", "Memory leak in camera service"]  # fmt: skip
        issues: dict[int, EmailMessage] = {}
        for index in range(count + assigned):
            mine = index < assigned
            number = self.random.randrange(3) + index % len(titles) * 3 + 1100
            title = titles[(number - 1100) // 3]
            first = issues.get(number)
            who = OWNER[0] if mine else self.pick(TEAM)
            body = (f"{who} {'was assigned' if mine else self.pick(['commented', 'changed the status', 'updated the priority'])} "
                    f"on RND-{number}.\n\nhttps://tracker.{COMPANY}/browse/RND-{number}")  # fmt: skip
            message = self.build(("Issue Tracker", f"tracker@{COMPANY}"), [OWNER[1]], f"[RND-{number}] {title}",
                                 body, self.when(), parent=first, headers={"Precedence": "bulk"} if self.random.random() < 0.3 else None)  # fmt: skip
            issues.setdefault(number, message)
            self.add(message, "tracker", True, important=mine)

    def admin_system(self, count: int) -> None:
        for _ in range(count):
            subject = self.pick([f"Your password expires in {self.random.randrange(1, 14)} days",
                                 f"Your mailbox is {self.random.randrange(80, 99)}% full",
                                 f"VPN certificate renewed for blr-{self.random.randrange(100, 999)}"])  # fmt: skip
            body = f"{subject}.\n\nThis notice was sent by the IT self-service system."
            self.add(
                self.build(
                    ("IT Admin", f"admin@{COMPANY}"), [OWNER[1]], subject, body, self.when()
                ),
                "admin-system",
                True,
            )

    def wiki(self, count: int) -> None:
        """Subjects name the page and the editor, so they almost never repeat."""
        pages = ["Camera HAL bring-up guide", "Orion release checklist", "Power budget 2026",
                 "Kernel coding conventions", "Vega test matrix", "On-call rota", "AI Platform roadmap",
                 "Lab equipment booking", "Modem field test results", "Design review template"]  # fmt: skip
        for _ in range(count):
            page, editor = self.pick(pages), self.pick(TEAM)
            subject = f'{editor} edited "{page}"'
            body = (f"{editor} made changes to {page}.\n\nView changes: https://wiki.{COMPANY}/pages/{self.random.randrange(10000, 99999)}\n\n"
                    "Stop watching this page | Manage notifications")  # fmt: skip
            self.add(
                self.build(("Wiki", f"wiki@{COMPANY}"), [OWNER[1]], subject, body, self.when()),
                "wiki",
                True,
            )

    def effort_report(self, count: int) -> None:
        """Lists the whole team, the person included, in every email."""
        for week in range(20, 20 + count):
            rows = "\n".join(
                f"{name:<22}{self.random.randrange(30, 48)} h" for name in sorted([OWNER[0], *TEAM])
            )
            body = f"Effort logged for week {week}:\n\n{rows}\n\nGenerated by the effort reporting tool."
            self.add(self.build(("Effort Reports", f"reports@{COMPANY}"), [LISTS["camera"]],
                                f"Weekly effort report - week {week}", body, self.when()), "effort-report", True)  # fmt: skip

    # Calendar

    def invitations(self, count: int) -> None:
        titles = ["Sprint review", "Design sync", "Orion architecture review", "1:1", "HQ weekly sync",
                  "Camera tuning session", "Release go/no-go", "Interview: Senior Engineer",
                  "Roadmap planning", "Security review", "Lab demo", "Quarterly business review"]  # fmt: skip
        for _ in range(count):
            name, _title = self.person()
            title, when = self.pick(titles), self.when()
            ics = (f"BEGIN:VCALENDAR\nMETHOD:REQUEST\nBEGIN:VEVENT\nSUMMARY:{title}\n"
                   f"DTSTART:{when:%Y%m%dT%H%M%SZ}\nORGANIZER:mailto:{address(name)}\nEND:VEVENT\nEND:VCALENDAR")  # fmt: skip
            message = self.build((name, address(name)), [OWNER[1], self.pick(list(LISTS.values()))], title,
                                 f"{title}\n\nJoin: https://meet.{COMPANY}/{self.random.randrange(10**8)}", when,
                                 outlook=True, headers={"Content-Class": "urn:content-classes:calendarmessage"}, calendar=ics)  # fmt: skip
            self.add(message, "invitation", False, calendar=True)

    def tagged_invitations(self, count: int) -> None:
        """Typed by people, with a tag but no calendar file."""
        topics = ["Tech talk: on-device LLMs", "Team lunch on Friday", "Hackathon kickoff",
                  "Brown bag: Rust in the kernel", "Farewell for Ravi", "Diwali celebration",
                  "Patent clinic", "Tech talk: camera ISP pipeline", "Book club", "Badminton tournament"]  # fmt: skip
        for _ in range(count):
            name, title = self.person()
            topic = self.pick(topics)
            body = f"Hi all,\n\nYou're invited to {topic.lower()} next week. Details to follow.\n\n{signature(name, title)}"
            self.add(self.build((name, address(name)), [LISTS["all"]], f"[Invitation] {topic}", body,
                                self.when(), outlook=True), "invitation-tag", False)  # fmt: skip

    def responses(self, count: int) -> None:
        for index in range(count):
            name, _title = self.person()
            answer, title = (
                self.pick(["Accepted", "Declined", "Tentative"]),
                self.pick(["Sprint review", "Design sync", "Roadmap planning"]),
            )
            ics = (
                f"BEGIN:VCALENDAR\nMETHOD:REPLY\nBEGIN:VEVENT\nSUMMARY:{title}\nEND:VEVENT\nEND:VCALENDAR"
                if index % 2
                else None
            )
            message = self.build((name, address(name)), [OWNER[1]], f"{answer}: {title}", "", self.when(), outlook=True,
                                 headers={"Content-Class": "urn:content-classes:calendarmessage"}, calendar=ics)  # fmt: skip
            self.add(message, "invitation-response", True, calendar=True)

    # People writing to many

    def broadcasts(self, sender: tuple[str, str], title: str, truth: str, subjects: list[str],
                   important: set[int], to: str) -> None:  # fmt: skip
        name, mail = sender
        for index, subject in enumerate(subjects):
            ask = index in important
            body = (f"Dear colleagues,\n\n{subject}. "
                    + ("Please complete this by the date above; it is mandatory for everyone in your grade.\n\n" if ask else "Details are below for your information.\n\n")
                    + signature(name, title))  # fmt: skip
            self.add(
                self.build((name, mail), [to], subject, body, self.when(), outlook=True),
                truth,
                False,
                important=ask,
            )

    # Conversations

    def conversations(self, asks: int, others: int) -> None:
        asks_text = [("Need your sign-off on the HDR tuning parameters", "Can you approve the attached values by Wednesday? The vendor build closes Thursday."),
                     ("Orion camera budget for Q1", "We need your estimate for headcount and lab time before the planning call on Monday."),
                     ("Patent disclosure review", "Could you review the draft claims and tell me which ones we should drop?"),
                     ("Interview panel tomorrow", "Can you take the system design round at 3pm? The candidate is for the Staff role."),
                     ("Escalation from HQ: preview freeze", "HQ is asking for a root cause today. Can you join a call at 5pm?"),
                     ("Decision needed: switch to the new ISP driver", "Please decide whether we move Vega to the new driver this sprint."),
                     ("Your review on the power design doc", "Waiting on your comments before I send it to Suwon. Can you look by Friday?"),
                     ("Promotion packet for Ananya", "Can you write the peer input for Ananya's packet by the 25th?")]  # fmt: skip
        threads: list[EmailMessage] = []
        for index in range(asks):
            (name, title), (subject, ask) = self.person(), asks_text[index % len(asks_text)]
            body = f"Hi Asha,\n\n{ask}\n\n{signature(name, title)}"
            message = self.build(
                (name, address(name)), [OWNER[1]], subject, body, self.when(), outlook=True
            )
            threads.append(self.add(message, "conversation-ask", False, important=True))
        fyi = ["Notes from the design sync", "Slides from today's review", "Thanks for the help yesterday",
               "Lab schedule update", "Minutes: Orion weekly", "FYI: vendor drop arrived", "Photos from the offsite",
               "Re-run results attached", "Summary of the HQ call", "Updated test matrix"]  # fmt: skip
        sent = 0
        # A colleague's weekly status and a manager's 1:1 notes repeat their subject, like a tool does.
        for week in range(36, 46):
            name, title = PEOPLE[0]
            self.add(self.build((name, address(name)), [LISTS["camera"]], f"Weekly status - week {week}",
                                f"Hi team,\n\nDone: camera HAL fixes.\nNext: HDR tuning.\nBlocked: none.\n\n{signature(name, title)}",
                                self.when(), cc=[OWNER[1]], outlook=True), "status-mail", False)  # fmt: skip
            sent += 1
        for day in range(8):
            name, title = PEOPLE[1]
            self.add(self.build((name, address(name)), [OWNER[1]], f"1:1 notes - {START + timedelta(days=14 * day):%d %b}",
                                f"Asha,\n\nNotes from today: hiring, Orion schedule, HQ visit.\n\n{signature(name, title)}",
                                self.when(), outlook=True), "one-on-one-notes", False)  # fmt: skip
            sent += 1
        while sent < others:
            (name, title) = self.person()
            if threads and self.random.random() < 0.3:
                parent = self.random.choice(threads)
                body = f"Thanks, noted.\n\n{signature(name, title)}\n\nFrom: {parent['From']}\n{parent.get_content()}"
                message = self.build((name, address(name)), [OWNER[1]], f"RE: {parent['Subject']}", body, self.when(),
                                     cc=[address(self.person()[0])], outlook=True, parent=parent)  # fmt: skip
            else:
                body = f"Hi all,\n\n{self.pick(fyi)} for reference.\n\n{signature(name, title)}"
                message = self.build((name, address(name)), [self.pick(list(LISTS.values()))], self.pick(fyi), body,
                                     self.when(), cc=[OWNER[1]], outlook=True)  # fmt: skip
            self.add(message, "conversation-fyi", False)
            sent += 1

    # Outside newsletters

    def newsletters(self, per_sender: int) -> None:
        senders = [("Tektrona", "news@mail.tektrona.example", "Tektrona Insights: {month} edition"),
                   ("SignalWorld", "weekly@signalworld.example", "SignalWorld Weekly #{n}: what's new in RF test"),
                   ("EmbeddedConf", "hello@embeddedconf.example", "EmbeddedConf 2027 - {topic}"),
                   ("CloudLab", "billing@cloudlab.example", "Your CloudLab usage summary for {month}")]  # fmt: skip
        topics = [
            "call for papers",
            "early-bird ends soon",
            "speakers announced",
            "workshops open",
            "last chance",
        ]
        for name, mail, pattern in senders:
            for index in range(per_sender):
                month = (START + timedelta(days=13 * index)).strftime("%B")
                subject = pattern.format(month=month, n=120 + index, topic=self.pick(topics))
                body = f"{subject}\n\nRead online: https://{mail.split('@')[1]}/{index}\n\nUnsubscribe | Manage preferences\n{name}, 1 Market St"
                headers = {
                    "List-Unsubscribe": f"<https://{mail.split('@')[1]}/u>",
                    "Precedence": "bulk",
                }
                self.add(
                    self.build(
                        (name, mail), [OWNER[1]], subject, body, self.when(), headers=headers
                    ),
                    "newsletter",
                    True,
                )


HR_SUBJECTS = [
    "Appraisal cycle 2026: timelines and next steps", "Updated leave policy from 1 December",
    "Wellness week: schedule and sign-up", "Health insurance renewal: add dependants",
    "New joiners this month", "Holiday list for 2027", "Referral bonus programme update",
    "Office transport routes from Monday", "Women in Tech mentoring circle", "Annual day registrations open",
    "Payroll for November", "Tax declaration window opens", "Learning portal: new courses",
    "Blood donation camp on Thursday", "Updated travel policy", "Code of conduct refresher",
    "Long service awards", "Parental leave policy changes", "Hybrid work guidelines", "Cafeteria vendor change",
    "Payroll for October", "Employee survey results", "Sports week fixtures", "Relocation support policy",
    "Internal job postings this week", "Wellness talk: sleep and focus", "Festival advance requests",
    "Updated grievance process", "Campus hiring drive volunteers", "Diversity council nominations",
    "Action required: self-review due 28 November", "Mandatory: POSH training due 30 November",
    "Year-end shutdown dates", "Gym membership tie-up", "Volunteering day options", "Payroll for September",
    "Insurance claim process update", "New HR business partners", "Exit interview survey changes",
    "Townhall recording now available",
]  # fmt: skip
ADMIN_NOTICES = [
    "Office closed on Friday for Diwali", "Block C lift maintenance on Sunday", "Cafeteria timings this week",
    "Parking lot resurfacing", "Fire drill on Wednesday", "Water supply interruption Saturday", "New visitor badge process",
    "Meeting room booking changes", "Pest control in Block A", "Power shutdown for maintenance", "Lost and found items",
    "Shuttle timings revised", "Floor 4 seating move", "Courier desk hours", "Air conditioning service",
    "Security audit next week", "Bike parking moved", "New pantry on floor 6", "Locker allocation", "Smoking zone relocated",
    "Canteen feedback form", "Ergonomic chair requests", "Rainwater harvesting work", "Generator testing Sunday",
    "Lift 3 out of service", "Fire extinguisher refill", "ID card renewal camp", "Office plants drive",
    "Mail room relocation", "Housekeeping schedule",
]  # fmt: skip
IT_NOTICES = [
    "Network maintenance on Saturday night", "New VPN client: rollout plan", "Email migration wave 3",
    "Phishing alert: fake payroll emails", "Laptop refresh for 2022 devices", "Wi-Fi upgrade in Block B",
    "Action needed: re-enrol your MFA device by Friday", "Printer fleet replacement", "New ticket portal",
    "Teams to Exchange calendar fix", "Software catalogue update", "Storage quota increase", "Git server downtime",
    "License server move", "Patch Tuesday schedule", "Mobile device policy update", "USB policy reminder",
    "SSO outage postmortem", "Backup policy changes", "Developer VM images refreshed", "Proxy changes for labs",
    "New screen recording tool", "Disk encryption rollout", "Old file shares retiring", "Helpdesk hours for Diwali",
]  # fmt: skip
LEADERSHIP = [
    "Mobile Platform R&D: Q3 results", "Principal engineers: roadmap inputs needed by Monday",
    "Welcome our new Director of AI Platform", "Org update for Camera and Multimedia", "Q4 priorities",
    "HQ visit next month", "Recognition: Orion launch team", "Hiring plan for 2027", "Innovation awards nominations",
    "Senior staff offsite agenda", "Feedback on the reorg", "Patent targets for the year",
    "Principal engineers: review panel volunteers by Friday", "Year in review", "Thank you for a strong quarter",
]  # fmt: skip


def build(directory: Path, seed: int = 7, marks: bool = True) -> list[Label]:
    """Writes 1,000 .eml files and labels.json into directory, and returns the labels."""
    box = Mailbox(seed, marks)
    box.plm(110, 10)
    box.swarm(90, 10)
    box.ro_bot(70, 5)
    box.qc(60, 8, 10)
    box.ci(40)
    box.tracker(50, 7)
    box.admin_system(30)
    box.wiki(30)
    box.effort_report(30)
    box.invitations(70)
    box.tagged_invitations(20)
    box.responses(30)
    box.broadcasts(("HR Communications", f"hr-comms@{COMPANY}"), "Human Resources", "hr", HR_SUBJECTS,
                   {3, 11, 30, 31}, LISTS["all"])  # fmt: skip
    box.broadcasts(
        ("IT Admin", f"admin@{COMPANY}"),
        "Facilities",
        "admin-notice",
        ADMIN_NOTICES,
        set(),
        LISTS["all"],
    )
    box.broadcasts(
        ("IT Team", f"it-team@{COMPANY}"),
        "IT Services",
        "it-notice",
        IT_NOTICES,
        {3, 6},
        LISTS["all"],
    )
    leader = PEOPLE[1]
    box.broadcasts(
        (leader[0], address(leader[0])),
        leader[1],
        "leadership",
        LEADERSHIP,
        {1, 12},
        LISTS["senior"],
    )
    box.conversations(42, 108)
    box.newsletters(15)
    directory.mkdir(parents=True, exist_ok=True)
    box.random.shuffle(box.items)
    labels: list[Label] = []
    for index, (message, label) in enumerate(box.items):
        name = f"{index:04d}.eml"
        (directory / name).write_bytes(bytes(message))
        labels.append(Label(name, label.truth, label.machine, label.calendar, label.important))
    (directory / "labels.json").write_text(
        json.dumps([asdict(label) for label in labels], indent=1)
    )
    return labels


if __name__ == "__main__":
    import sys

    made = build(Path(sys.argv[1]))
    print(f"{len(made)} emails, {sum(label.important for label in made)} important")
