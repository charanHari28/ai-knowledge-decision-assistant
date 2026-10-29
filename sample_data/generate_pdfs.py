"""Generates the sample knowledge-base PDFs for two demo organizations.

    python sample_data/generate_pdfs.py

Org A: Greenfield University (student affairs)  -> sample_data/greenfield_university/*.pdf
Org B: Nimbus Technologies (HR policies)        -> sample_data/nimbus_technologies/*.pdf
Also writes sample_data/invalid/ files used to demo validation errors.
"""
from pathlib import Path

from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import ListFlowable, ListItem, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).resolve().parent
ss = getSampleStyleSheet()
TITLE = ParagraphStyle("t", parent=ss["Title"], fontSize=20, spaceAfter=6)
SUB = ParagraphStyle("s", parent=ss["Normal"], alignment=TA_CENTER, textColor="#555555", spaceAfter=18)
H1 = ParagraphStyle("h1", parent=ss["Heading1"], fontSize=15, spaceBefore=10, spaceAfter=6, textColor="#1f3a5f")
H2 = ParagraphStyle("h2", parent=ss["Heading2"], fontSize=12, spaceBefore=8, spaceAfter=4, textColor="#1f3a5f")
BODY = ParagraphStyle("b", parent=ss["Normal"], fontSize=10.5, leading=15, spaceAfter=6)


def numbered(items):
    return ListFlowable([ListItem(Paragraph(i, BODY)) for i in items], bulletType="1", bulletFormat="%s.", leftIndent=14)


def bullets(items):
    return ListFlowable([ListItem(Paragraph(i, BODY)) for i in items], bulletType="bullet", leftIndent=14)


def table(rows):
    t = Table(rows, hAlign="LEFT", colWidths=[6 * cm, 9 * cm])
    t.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), "#e8eef6"),
        ("GRID", (0, 0), (-1, -1), 0.4, "#9aa8b8"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def build(path: Path, title: str, subtitle: str, story):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=2.2 * cm, rightMargin=2.2 * cm, topMargin=2 * cm, bottomMargin=2 * cm, title=title)

    def footer(canvas, d):
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor("#777777")
        canvas.drawString(2.2 * cm, 1.2 * cm, f"{title} — Page {d.page}")

    doc.build([Paragraph(title, TITLE), Paragraph(subtitle, SUB)] + story, onFirstPage=footer, onLaterPages=footer)
    print("wrote", path.relative_to(HERE.parent))


P = lambda t: Paragraph(t, BODY)  # noqa: E731


# =====================================================================  ORG A
def greenfield():
    out = HERE / "greenfield_university"
    build(out / "Scholarship_Rules.pdf", "Scholarship Rules 2026-27", "Greenfield University — Office of Student Financial Aid", [
        Paragraph("1. General Principles", H1),
        P("Greenfield University offers three institutional scholarships: the Merit Scholarship, the Sports Excellence Scholarship and Need-Based Financial Aid. These rules apply to all undergraduate students for the 2026-27 academic year."),
        P("A student may hold only one institutional scholarship at a time. A student who qualifies for more than one scholarship must choose one; the other application will be withdrawn. External (government or private) scholarships may be held together with an institutional scholarship."),
        P("Scholarships are awarded for one academic year and must be renewed each year. All amounts are credited directly against tuition fees; no cash is paid to students."),
        Paragraph("Summary of awards", H2),
        table([["Scholarship", "Annual value"],
               ["Merit Scholarship", "Rs. 50,000 per year plus a 25% tuition waiver"],
               ["Sports Excellence Scholarship", "Rs. 40,000 per year"],
               ["Need-Based Financial Aid", "Up to 100% of tuition, based on family income"]]),
        PageBreak(),
        Paragraph("2. Merit Scholarship", H1),
        P("The Merit Scholarship recognises sustained academic excellence. It is worth Rs. 50,000 per year plus a 25% tuition waiver. Up to 40 Merit Scholarships are awarded each year, and where more eligible students apply than awards are available, students are ranked by cumulative GPA."),
        Paragraph("Merit Scholarship Eligibility Criteria", H2),
        numbered([
            "The student must be enrolled in Year 2 or above of an undergraduate programme.",
            "The student must have a minimum cumulative GPA of 8.5 on a 10-point scale.",
            "The student must have attendance of at least 75% in the previous academic year.",
            "The student must not hold any other institutional scholarship, including the Sports Excellence Scholarship.",
        ]),
        Paragraph("Renewal", H2),
        P("The Merit Scholarship is renewed automatically if the student maintains a cumulative GPA of 8.5 or above and has no disciplinary action recorded during the year."),
        PageBreak(),
        Paragraph("3. Sports Excellence Scholarship", H1),
        P("The Sports Excellence Scholarship supports students who represent the university in competitive sport. It is worth Rs. 40,000 per year and includes free access to the university training centre."),
        Paragraph("Sports Excellence Scholarship Eligibility Criteria", H2),
        numbered([
            "The student must have represented the university at state level or above in the previous 12 months.",
            "The student must have a minimum cumulative GPA of 6.0.",
            "The student must have attendance of at least 65%, after counting approved sports leave.",
        ]),
        Paragraph("4. Need-Based Financial Aid", H1),
        P("Need-Based Financial Aid covers between 25% and 100% of tuition depending on annual family income. Students with family income below Rs. 3 lakh receive a full tuition waiver."),
        Paragraph("Need-Based Financial Aid Eligibility Criteria", H2),
        numbered([
            "The annual family income must not exceed Rs. 6,00,000 (6 lakh).",
            "The student must have a minimum cumulative GPA of 6.5.",
            "The student must be a full-time student.",
        ]),
        PageBreak(),
        Paragraph("5. Application Procedure", H1),
        P("Applications for all institutional scholarships open on 1 July and close on 31 August each year. Late applications are not accepted."),
        numbered([
            "Log in to the Student Portal and open Financial Aid &gt; Scholarships.",
            "Select the scholarship and complete the online application form.",
            "Upload the required documents: latest grade sheet, attendance certificate, and, for Need-Based Financial Aid, the family income certificate issued by the Tahsildar or employer.",
            "Submit the application. You will receive an acknowledgement number by email.",
            "The Scholarship Committee publishes results on the Student Portal by 30 September.",
        ]),
        Paragraph("6. Appeals", H1),
        P("A student whose application is rejected may appeal in writing to the Dean of Student Affairs within 10 working days of the result. Appeals are decided within 15 working days and the decision of the Dean is final."),
        Paragraph("7. Contact", H1),
        P("Office of Student Financial Aid, Admin Block Room 104. Email: finaid@greenfield.example. Office hours: 9:30 AM to 4:30 PM, Monday to Friday."),
    ])

    build(out / "Academic_Policies.pdf", "Academic Policies Handbook", "Greenfield University — Office of the Registrar", [
        Paragraph("1. Attendance", H1),
        P("Students must maintain a minimum of 75% attendance in each course to be allowed to sit for the end-semester examination. Students below 75% are marked 'Detained' in that course and must repeat it."),
        P("Attendance shortage of up to 10% can be condoned on medical grounds if a medical certificate is submitted to the department within 7 days of returning to class. Condonation is never granted below 65% attendance."),
        Paragraph("2. Grading System", H1),
        P("Courses are graded on a 10-point scale: O (10), A+ (9), A (8), B+ (7), B (6), C (5), and F (0, fail). The cumulative GPA (CGPA) is the credit-weighted average of all grade points earned."),
        Paragraph("3. Academic Probation", H1),
        P("A student whose CGPA falls below 5.0 at the end of any semester is placed on academic probation. Students on probation may register for at most 18 credits and must meet their faculty advisor every two weeks. Probation is lifted when the CGPA rises to 5.0 or above."),
        PageBreak(),
        Paragraph("4. Re-evaluation of Answer Scripts", H1),
        P("A student who is not satisfied with the marks awarded in an end-semester examination may apply for re-evaluation."),
        numbered([
            "Apply on the Student Portal under Examinations &gt; Re-evaluation within 7 days of the publication of results.",
            "Pay the re-evaluation fee of Rs. 500 per subject online.",
            "The answer script is re-evaluated by an examiner who did not evaluate it the first time.",
            "If the marks change by 10% or more, the revised marks replace the original marks and the fee is refunded.",
            "Re-evaluation results are published within 21 days of the application deadline.",
        ]),
        Paragraph("5. Supplementary Examinations", H1),
        P("Students who fail a course may take the supplementary examination held in July. The supplementary examination fee is Rs. 1,000 per course, and the maximum grade awarded in a supplementary examination is B."),
    ])

    build(out / "Hostel_Handbook.pdf", "Hostel Handbook", "Greenfield University — Residential Services", [
        Paragraph("1. Hostel Accommodation", H1),
        P("The university provides separate hostels for men and women with single, double and triple occupancy rooms. Rooms are allotted for one academic year at a time."),
        Paragraph("Hostel Accommodation Eligibility Criteria", H2),
        numbered([
            "The student must be a full-time student.",
            "The student's permanent home address must be more than 50 km from the campus.",
            "The student must not have any pending fee dues.",
        ]),
        Paragraph("2. Fees", H1),
        table([["Room type", "Fee per year (incl. mess)"],
               ["Single occupancy", "Rs. 1,20,000"],
               ["Double occupancy", "Rs. 95,000"],
               ["Triple occupancy", "Rs. 80,000"]]),
        Spacer(1, 8),
        Paragraph("3. Rules and Timings", H1),
        bullets([
            "Hostel gates close at 10:30 PM. Late entry requires prior permission from the warden.",
            "Day visitors are allowed in the visitors' lounge from 4:00 PM to 7:00 PM. Visitors are not permitted inside rooms.",
            "Mess timings: breakfast 7:30-9:30 AM, lunch 12:30-2:00 PM, dinner 7:30-9:30 PM.",
            "Cooking appliances, alcohol and smoking are strictly prohibited inside the hostel.",
        ]),
        Paragraph("4. Vacating the Hostel", H1),
        P("Students must vacate their rooms within 7 days of the last examination of the academic year. The refundable caution deposit of Rs. 10,000 is returned within 30 days after the room is inspected."),
    ])


# =====================================================================  ORG B
def greenfield_extra():
    """Three more Greenfield documents (added for extra demo questions)."""
    out = HERE / "greenfield_university"
    build(out / "Placement_Policy.pdf", "Training and Placement Policy 2026-27", "Greenfield University — Career Development Centre", [
        Paragraph("1. Campus Placements", H1),
        P("The Career Development Centre (CDC) organises campus placements every year from August to March. Over 120 companies visited the campus in 2025-26, and the highest package offered was Rs. 32 lakh per annum."),
        Paragraph("Campus Placement Eligibility Criteria", H2),
        numbered([
            "The student must be enrolled in the final year of an undergraduate programme.",
            "The student must have a minimum cumulative GPA of 7.0.",
            "The student must have attendance of at least 75% in the current academic year.",
            "The student must not have any active backlogs.",
        ]),
        Paragraph("One Student, One Job", H2),
        P("A student who accepts a job offer is not allowed to sit for further placement drives. Students with an offer below Rs. 6 lakh per annum may apply once more for a dream company, with written permission from the CDC head."),
        PageBreak(),
        Paragraph("2. Summer Internships", H1),
        P("Summer internships of 8 to 12 weeks earn 4 academic credits. Internships may be with companies, research labs or NGOs, in India or online."),
        Paragraph("Internship Credit Eligibility Criteria", H2),
        numbered([
            "The student must be enrolled in Year 3 or above.",
            "The student must have a minimum cumulative GPA of 6.0.",
            "The internship must not exceed 12 weeks.",
        ]),
        Paragraph("How to Register an Internship for Credit", H2),
        numbered([
            "Get the offer letter approved by your department's faculty coordinator before you start.",
            "Register the internship on the Student Portal under Career &gt; Internships within 7 days of starting.",
            "Submit a weekly progress report signed by your company mentor.",
            "Within 15 days of finishing, submit the final report and the completion certificate to the CDC.",
            "Credits are added to your grade sheet after a 15-minute presentation to the department panel.",
        ]),
        Paragraph("3. Contact", H1),
        P("Career Development Centre, Block C, 2nd floor. Email: cdc@greenfield.example. Office hours: 10:00 AM to 5:00 PM, Monday to Saturday."),
    ])

    build(out / "Library_and_IT_Services.pdf", "Library and IT Services Guide", "Greenfield University — Central Library and IT Helpdesk", [
        Paragraph("1. Library Timings and Borrowing", H1),
        P("The Central Library is open from 8:00 AM to 11:00 PM on weekdays and 9:00 AM to 6:00 PM on weekends. During end-semester examinations it stays open 24 hours."),
        table([["Member", "Books at a time / loan period"],
               ["Undergraduate student", "4 books for 14 days"],
               ["Postgraduate student", "6 books for 30 days"],
               ["Faculty", "10 books for 90 days"]]),
        Spacer(1, 8),
        P("Books can be renewed twice online if no one has reserved them. The late-return fine is Rs. 5 per book per day. A lost book must be replaced or paid for at twice its current price."),
        Paragraph("2. Laptop Loan Scheme", H1),
        P("Students who do not own a laptop can borrow a university laptop for one semester at a time, free of charge. 150 laptops are available each semester on a first-come, first-served basis."),
        Paragraph("Laptop Loan Eligibility Criteria", H2),
        numbered([
            "The student must be a full-time student.",
            "The annual family income must not exceed Rs. 5,00,000 (5 lakh).",
            "The student must not have any pending library fines.",
        ]),
        P("A damaged laptop must be reported to the IT Helpdesk within 48 hours. Repair costs caused by negligence are charged to the student."),
        PageBreak(),
        Paragraph("3. Campus Wi-Fi", H1),
        P("Every student gets a Wi-Fi account with a daily limit of 5 GB. The network name is GF-Campus. Up to 3 devices can be connected at the same time."),
        Paragraph("How to Reset Your Wi-Fi or Portal Password", H2),
        numbered([
            "Go to the IT self-service page at it.greenfield.example and click Forgot Password.",
            "Enter your student ID and the mobile number registered with the university.",
            "Enter the one-time password sent by SMS.",
            "Choose a new password with at least 10 characters, including a number and a symbol.",
            "If the reset fails, visit the IT Helpdesk in the Library basement with your student ID card.",
        ]),
    ])

    build(out / "Fee_Payment_and_Refund_Policy.pdf", "Fee Payment and Refund Policy", "Greenfield University — Accounts Office", [
        Paragraph("1. Fee Payment Schedule", H1),
        P("Tuition fees are paid per semester. The fee for the odd semester is due by 15 July and for the even semester by 15 December. Fees can be paid online on the Student Portal by UPI, net banking, debit card or credit card."),
        P("A late fee of Rs. 100 per day is charged after the due date, up to a maximum of Rs. 3,000. Students whose fees are unpaid 30 days after the due date are not allowed to register for courses."),
        Paragraph("2. Instalment Plan", H1),
        P("Students can pay each semester's tuition fee in three equal monthly instalments instead of a single payment. There is no interest on instalments."),
        Paragraph("Instalment Plan Eligibility Criteria", H2),
        numbered([
            "The annual family income must not exceed Rs. 8,00,000 (8 lakh).",
            "The student must not have any pending fee dues from a previous semester.",
            "The student must be enrolled in Year 2 or above.",
        ]),
        Paragraph("How to Apply for the Instalment Plan", H2),
        numbered([
            "Log in to the Student Portal and open Fees &gt; Instalment Plan at least 10 days before the fee due date.",
            "Upload the family income certificate.",
            "The Accounts Office approves or rejects the request within 5 working days.",
            "Once approved, the instalment dates appear on your fee statement.",
        ]),
        PageBreak(),
        Paragraph("3. Refund on Withdrawal", H1),
        table([["When you withdraw", "Tuition fee refunded"],
               ["Before classes start", "100% minus Rs. 1,000 processing fee"],
               ["Within 15 days of classes starting", "80%"],
               ["Within 30 days of classes starting", "50%"],
               ["After 30 days", "No refund"]]),
        Spacer(1, 8),
        P("Hostel and mess fees are refunded for complete months not used. Refunds are credited to the original payment method within 30 working days of approval."),
    ])


def nimbus():
    out = HERE / "nimbus_technologies"
    build(out / "Leave_Policy.pdf", "Leave Policy", "Nimbus Technologies Pvt. Ltd. — Human Resources (effective 1 April 2026)", [
        Paragraph("1. Leave Entitlements", H1),
        table([["Leave type", "Entitlement"],
               ["Annual (privilege) leave", "24 working days per calendar year"],
               ["Sick leave", "12 working days per calendar year"],
               ["Maternity leave", "26 weeks (paid)"],
               ["Paternity leave", "10 working days (paid)"],
               ["Bereavement leave", "5 working days"]]),
        Spacer(1, 8),
        P("Annual leave accrues at 2 days per month. Up to 10 days of unused annual leave can be carried forward to the next year; any balance above 10 days lapses on 31 December. Sick leave cannot be carried forward."),
        P("Sick leave of more than 2 consecutive days requires a medical certificate uploaded to the HRMS within 3 days of returning to work."),
        Paragraph("2. How to Apply for Leave", H1),
        numbered([
            "Log in to the HRMS portal and open Leave &gt; Apply.",
            "Select the leave type, dates and add a short reason.",
            "Annual leave must be applied for at least 7 days in advance; leave of 5 or more consecutive days needs 14 days' notice.",
            "Your reporting manager approves or rejects the request within 2 working days.",
            "Approved leave appears on the team calendar automatically.",
        ]),
        PageBreak(),
        Paragraph("3. Sabbatical Leave", H1),
        P("Sabbatical Leave is unpaid leave of 1 to 6 months for higher studies, research or personal development. The employee's position is held for them during the sabbatical."),
        Paragraph("Sabbatical Leave Eligibility Criteria", H2),
        numbered([
            "The employee must have a minimum of 36 months of continuous service.",
            "The employee must have a performance rating of at least 4 in the most recent appraisal cycle.",
            "The employee must not be on a Performance Improvement Plan.",
        ]),
        P("Sabbatical requests must be submitted to HR at least 60 days before the planned start date and require approval from the department head."),
    ])

    build(out / "Work_From_Home_Policy.pdf", "Work From Home and Remote Work Policy", "Nimbus Technologies Pvt. Ltd. — Human Resources", [
        Paragraph("1. Hybrid Working", H1),
        P("All employees follow a hybrid model: 3 days per week in the office and up to 2 days per week working from home. Teams agree on common office days with their manager. Core collaboration hours are 11:00 AM to 4:00 PM IST."),
        P("Each employee receives a one-time home-office allowance of Rs. 15,000, claimable through the expense portal within the first 6 months of joining."),
        Paragraph("2. Remote Work Abroad", H1),
        P("Employees may work remotely from outside India for a limited period, for example while visiting family. Payroll and tax remain in India."),
        Paragraph("Remote Work Abroad Eligibility Criteria", H2),
        numbered([
            "The employee must have a minimum of 12 months of continuous service.",
            "The employee must have successfully completed probation.",
            "The employee must have a performance rating of at least 3 in the most recent appraisal cycle.",
            "The request must not exceed 30 working days per calendar year.",
        ]),
        P("Requests must be raised on the HRMS under Remote Work &gt; Abroad at least 21 days before travel and approved by the reporting manager and the IT Security team. Employees working on client projects that restrict offshore access are not permitted to work abroad."),
        Paragraph("3. Equipment and Security", H1),
        P("Company laptops must be connected through the corporate VPN at all times when working outside the office. Public Wi-Fi may only be used with the VPN enabled. Loss of a device must be reported to IT Security within 24 hours."),
    ])

    build(out / "Learning_Assistance_Policy.pdf", "Learning and Education Assistance Policy", "Nimbus Technologies Pvt. Ltd. — Learning & Development", [
        Paragraph("1. Purpose", H1),
        P("Nimbus Technologies supports employees who pursue job-related learning. Under the Education Reimbursement program the company reimburses up to Rs. 1,50,000 per financial year in tuition and examination fees."),
        Paragraph("2. Education Reimbursement", H1),
        Paragraph("Education Reimbursement Eligibility Criteria", H2),
        numbered([
            "The employee must have a minimum of 12 months of continuous service.",
            "The employee must have a performance rating of at least 3 in the most recent appraisal cycle.",
            "The employee must not be on a Performance Improvement Plan.",
            "The course type must be one of: degree program, professional certification, or online course.",
        ]),
        Paragraph("3. Reimbursement Process", H1),
        numbered([
            "Get pre-approval from your manager and the L&amp;D team before enrolling, using the Learning &gt; Education Assistance form on the HRMS.",
            "Pay the course fee yourself and keep the receipts.",
            "After completing the course, submit the receipts and proof of completion (certificate or grade sheet) within 60 days.",
            "Reimbursement is credited with the next month's salary.",
        ]),
        Paragraph("4. Service Commitment", H1),
        P("Employees who receive more than Rs. 50,000 in reimbursement must remain with the company for 12 months after the course ends. If the employee resigns earlier, the reimbursed amount is recovered on a pro-rata basis from the final settlement."),
    ])


def nimbus_extra():
    """Three more Nimbus documents (added for extra demo questions)."""
    out = HERE / "nimbus_technologies"
    build(out / "Travel_and_Relocation_Policy.pdf", "Travel and Relocation Policy", "Nimbus Technologies Pvt. Ltd. — Finance & HR", [
        Paragraph("1. Business Travel", H1),
        P("All business travel must be booked through the company travel desk on the HRMS at least 7 days before the trip. Flights are economy class. Flights longer than 6 hours may be booked in premium economy with approval from the department head."),
        table([["Expense", "Daily allowance (per diem)"],
               ["Metro cities (Bengaluru, Mumbai, Delhi, etc.)", "Rs. 3,500 per day"],
               ["Other cities in India", "Rs. 2,500 per day"],
               ["International travel", "USD 75 per day"]]),
        Spacer(1, 8),
        P("Hotel stays are booked by the travel desk. Local taxis and meals are covered by the daily allowance; no separate bills are needed."),
        Paragraph("How to Claim Travel Expenses", H2),
        numbered([
            "Open Expenses &gt; New Claim on the HRMS within 15 days of returning from the trip.",
            "Select the approved trip and add any expenses not covered by the travel desk.",
            "Upload receipts for every expense above Rs. 500.",
            "Your reporting manager approves the claim, then Finance verifies it.",
            "The amount is paid with the next salary.",
        ]),
        PageBreak(),
        Paragraph("2. Relocation Assistance", H1),
        P("Employees who move to a different Nimbus office at the company's request, or through an internal transfer, receive a relocation package: one-way travel for the family, shifting of household goods up to Rs. 1,00,000, and 14 days of company-paid temporary accommodation."),
        Paragraph("Relocation Assistance Eligibility Criteria", H2),
        numbered([
            "The employee must have a minimum of 6 months of continuous service.",
            "The new office must be more than 100 km from the current office.",
            "The employee must not be serving a notice period.",
        ]),
        P("An employee who resigns within 12 months of relocating must repay the relocation package in full."),
    ])

    build(out / "Internal_Job_Posting_and_Referral_Policy.pdf", "Internal Job Posting and Employee Referral Policy", "Nimbus Technologies Pvt. Ltd. — Talent Acquisition", [
        Paragraph("1. Internal Job Posting (IJP)", H1),
        P("Open positions are posted on the IJP board on the HRMS for 7 days before they are advertised outside the company. Employees can apply to at most 2 internal positions at the same time."),
        Paragraph("Internal Job Posting Eligibility Criteria", H2),
        numbered([
            "The employee must have a minimum of 18 months of continuous service in the current role.",
            "The employee must have a performance rating of at least 3 in the most recent appraisal cycle.",
            "The employee must not be on a Performance Improvement Plan.",
        ]),
        Paragraph("How to Apply for an Internal Position", H2),
        numbered([
            "Inform your current reporting manager before applying. This is mandatory.",
            "Apply on the HRMS under Careers &gt; Internal Jobs.",
            "Talent Acquisition schedules interviews with the hiring team within 10 working days.",
            "If selected, the release date is agreed between both managers and must be within 60 days.",
        ]),
        PageBreak(),
        Paragraph("2. Employee Referral Programme", H1),
        P("Employees who refer candidates who are hired receive a referral bonus. The bonus is paid in two equal parts: half after the new hire joins, and half after the new hire completes 6 months."),
        table([["Role level", "Referral bonus"],
               ["Associate / Engineer", "Rs. 25,000"],
               ["Senior Engineer / Lead", "Rs. 50,000"],
               ["Manager and above", "Rs. 75,000"]]),
        Spacer(1, 8),
        P("HR team members and the hiring manager for the position are not eligible for referral bonuses. Referrals are submitted on the HRMS under Careers &gt; Refer a Friend, with the candidate's CV."),
    ])

    build(out / "Health_and_Wellness_Benefits.pdf", "Health and Wellness Benefits", "Nimbus Technologies Pvt. Ltd. — Total Rewards", [
        Paragraph("1. Group Medical Insurance", H1),
        P("Every employee is covered from the date of joining under a family floater health insurance policy of Rs. 5,00,000 per year. The policy covers the employee, spouse and up to two children. Cashless treatment is available at more than 8,000 network hospitals."),
        P("Employees can add their parents or parents-in-law by paying an additional premium of Rs. 12,000 per year, deducted from salary. Parents can only be added during the annual enrolment window in April."),
        Paragraph("How to Make a Reimbursement Claim", H2),
        numbered([
            "Inform the insurance helpdesk within 48 hours of a planned or emergency hospital admission.",
            "Pay the hospital bill and collect the discharge summary, original bills and test reports.",
            "Submit the claim on the insurer's portal within 30 days of discharge.",
            "Claims are settled within 21 days, directly to your salary bank account.",
        ]),
        PageBreak(),
        Paragraph("2. Wellness Allowance", H1),
        P("Nimbus reimburses up to Rs. 18,000 per year for gym memberships, sports coaching, yoga classes or fitness apps. Claims are made quarterly through the expense portal."),
        Paragraph("Wellness Allowance Eligibility Criteria", H2),
        numbered([
            "The employee must be a full-time employee.",
            "The employee must have successfully completed probation.",
        ]),
        Paragraph("3. Employee Assistance Programme", H1),
        P("Free and confidential counselling is available 24 hours a day for employees and their families, up to 6 sessions per year. Call the helpline at 1800-200-4455 or book through the wellness app."),
    ])


def invalid_files():
    out = HERE / "invalid"
    out.mkdir(parents=True, exist_ok=True)
    (out / "not_really_a_pdf.pdf").write_text("This is plain text pretending to be a PDF.")
    (out / "notes.txt").write_text("Text files are not accepted.")
    long_story = []
    for i in range(1, 23):
        long_story += [Paragraph(f"Chapter {i}", H1), P("Filler content for page-limit testing. " * 30), PageBreak()]
    build(out / "Too_Many_Pages_22.pdf", "Oversized Handbook", "Used to demonstrate the 20-page limit", long_story)
    print("wrote invalid/ samples")


if __name__ == "__main__":
    greenfield()
    greenfield_extra()
    nimbus()
    nimbus_extra()
    invalid_files()
