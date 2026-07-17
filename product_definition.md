# Career CoDesk: AI Career Guidance Operations Copilot

## Core Conclusion
This project does not solve the problem of "students not knowing what career to choose," nor does it address the issue of "colleges lacking career assessment tools." Instead, it solves the execution gap: once a college has collected student needs, it lacks the capacity to translate those needs into actionable, timely support using its limited number of Career Advisers.

The precise definition of the product is:
**AI Career Guidance Operations Copilot**: Translates scattered student needs data into actionable group activities, 1-to-1 priority queues, meeting preparation materials, and follow-up action records for the current week.

Both research reports point to this "execution gap." While the front end can identify needs through check-ins, questionnaires, and RAG triage, colleges still need to decide who to process first, which students can be grouped together, what each Adviser should do, and how to leave evidence of intervention. The second report also indicates that digital tracking and data collection have a relatively higher level of commercialization, while the capability to truly translate diagnostic results into personalized interventions remains insufficient.

---

## I. Specific Problems the Project Solves
Suppose a college has:
* **2 Career Advisers**;
* **500 students** who are about to graduate or are entering critical decision-making stages;
* A student **Career Check-in** spreadsheet, questionnaire, or Excel sheet;
* A large amount of **scattered free-text responses**;
* **Limited Adviser working hours**.

### Current Process (Manual & Fragmented)
```
Collect student responses
   ↓
Manually read each response
   ↓
Manually judge needs
   ↓
Manually decide who needs a 1-to-1 meeting
   ↓
Manually organize workshops
   ↓
Re-understand student background before meetings
   ↓
Write notes after meetings
   ↓
Follow up
```
The problem is not that any single step is completely impossible, but that the entire process relies on manual patching and administrative overhead.

### MVP Process (AI-Enabled & Orchestrated)
```
Upload anonymous student data
   ↓
AI understands and standardizes needs
   ↓
AI detects cohort-level patterns
   ↓
System calculates resource and time constraints
   ↓
AI generates an executable weekly intervention plan
   ↓
AI prepares individual student meeting briefs
   ↓
Staff review and modify
   ↓
AI generates follow-up records
```

This MVP solves four specific problems:

### 1. Data is visible, but cannot be quickly understood
Student answers are usually non-standardized:
* *"I’m thinking about university but might do an apprenticeship because I need money."*
* *"Not sure what to do. I work at Tesco and like helping customers."*

AI can transform these responses into structured data:
```json
{
  "intended_pathway": ["university", "apprenticeship"],
  "decision_status": "undecided",
  "primary_barrier": "financial concern",
  "existing_experience": "part-time retail",
  "recommended_support": [
    "option comparison",
    "apprenticeship funding information"
  ]
}
```
This saves staff from manually reading hundreds of open-ended questionnaires.

### 2. Colleges know who has needs, but not how to organize services
Traditional RAG triage only tells staff:
* **Green**
* **Amber**
* **Red**

It does not answer:
* If 18 students are stuck on apprenticeship applications, should we organize a group workshop?
* Which students have deadlines within two weeks?
* Which issues must be handled 1-to-1?
* Are the current Adviser hours sufficient?
* Which students need additional follow-up rather than just a single meeting?

The product is responsible for converting "classification" further into an "operational plan."

### 3. Career Advisers waste time on preparation and administrative tasks
Before a meeting, advisers need to re-read student information. After the meeting, they must generate:
* Guidance notes
* Agreed actions
* Referral notes
* Follow-up messages
* Evidence records

AI can prepare drafts for all of these, which are ultimately approved by the Adviser.

### 4. Colleges struggle to prove that interventions actually happened
Reports emphasize that colleges do not just need to prove they "hosted an event"; they need to demonstrate the link between student needs, interventions, and subsequent actions.

The system forms a simple trail:
```
Initial need 
   ↓ 
Recommended intervention 
   ↓ 
Adviser-approved intervention 
   ↓ 
Agreed actions 
   ↓ 
Follow-up status
```
While it does not automatically guarantee Gatsby or Ofsted compliance, it significantly reduces the workload of organizing evidence.

---

## II. How to Embed More AI Capabilities in the MVP
Instead of adding multiple chat boxes for the sake of "having AI," embed AI into five specific workflow nodes:

### AI Feature 1: Intake Interpreter
* **Input**: Student structured options and a piece of free text:
  * Course: *Level 3 Health and Social Care*
  * Future plan: *Not sure*
  * Student comment: *"I want to work in healthcare but I don't think my grades are good enough for university."*
* **AI Output**:
  * **Pathway interest**: Healthcare
  * **Decision stage**: Exploring options
  * **Main barriers**:
    * Low academic confidence
    * Limited awareness of non-university routes
  * **Suggested preparation**:
    * NHS apprenticeship information
    * Compare university and apprenticeship routes
    * Review actual entry requirements
* **AI Value**: Converts unstructured answers into standardized fields.
* **Technical details**: Uses LLM structured output, JSON schema, fixed tag system, and outputs `unknown` instead of guessing when uncertain.

### AI Feature 2: Barrier Classification
Establish a finite, transparent barrier classification system, such as:
* No clear direction
* Qualification uncertainty
* Application skills
* Interview preparation
* Financial concern
* Transport/access
* Low confidence
* Limited labour-market knowledge
* Deadline pressure
* Requires human review

AI recommends tags, which staff can modify. This is more valuable than just outputting Red/Amber/Green because the Career Team needs to know *why* students need help and *how* support can be organized.

> [!WARNING]
> Do not let the model identify "mental health issues," "safeguarding risks," or "NEET probability." If sensitive, vague, or unmanageable information appears, the model must output `Human review required`.

### AI Feature 3: Cohort Pattern Finder
This is the most commercially valuable AI feature in the Demo.
The system performs semantic clustering on the needs of 100 students, for example, finding:
* **24 students**: Do not understand apprenticeship applications
* **16 students**: Unsure whether their grades meet university requirements
* **11 students**: Need interview preparation
* **8 students**: Have no defined pathway
* **4 students**: Require individual human review

AI not only classifies but also explains *why* these students can form a single intervention group.
* **Technical details**: Uses embeddings, predefined categories, LLM cluster naming, and minimum cohort size rules.
* **Crucial workflow**: To avoid pure LLM hallucination, use a hybrid flow: AI recommends tags → Program aggregates by tags → AI generates group names and explanations.

### AI Feature 4: Capacity and Intervention Orchestrator
The system reads:
* Number of students
* Types of issues
* Application deadlines
* Number of Advisers
* Available weekly adviser hours
* Maximum workshop size
* Individual cases requiring manual review

Then, it generates a **Recommended Weekly Plan**:
* **Monday**: Apprenticeship application workshop (18 learners, 60 minutes)
* **Tuesday**: University entry requirements clinic (12 learners, 45 minutes)
* **Wednesday**: Six individual guidance sessions (Priority: approaching deadlines)
* **Thursday**: Interview preparation workshop (9 learners, 60 minutes)
* **Friday**: Four human-review cases (45 minutes each)

Here, duties are separated:
* **Program/Engine handles**: Time summation, Adviser capacity, deadline sorting, workshop capacity limits, schedule conflicts, and hard business rules.
* **AI handles**: Recommending intervention formats based on barrier types, explaining why it was organized this way, generating activity outlines, and proposing alternative plans.
* *Do not let the LLM handle arithmetic and scheduling constraints directly.* AI is suitable for proposing scenarios; a rule engine verifies execution feasibility.

### AI Feature 5: Adviser Brief Generator
When a staff member clicks on a student, it generates a one-page brief:
* **Current situation**: The learner is studying Level 3 Health and Social Care and is interested in healthcare. They currently assume that university is the only route but are concerned about grades.
* **Suggested discussion points**:
  1. Clarify which healthcare roles are of interest.
  2. Check actual university entry requirements.
  3. Explore NHS and healthcare apprenticeships.
  4. Discuss financial implications of each route.
* **Do not assume**:
  * That the learner is academically unsuitable for university.
  * That an apprenticeship is necessarily preferable.
  * That low confidence reflects low ability.
* **Suggested outcome**: The learner should leave the session with two realistic pathways and one concrete next action for each.

This is much better than a generic summary because it instructs the Adviser on: what is already known, what to ask, what not to assume, and what outcomes the session should produce.

### AI Feature 6: Action Plan Generator
After the meeting, the Adviser inputs a few brief notes:
* *"Interested in occupational therapy. Will check three university courses. Also wants to examine degree apprenticeships. Needs support with personal statement."*

AI converts this into a structured action plan:
* **Action 1**: Compare entry requirements for three occupational therapy courses. (Owner: Student, Due: 25 October)
* **Action 2**: Identify at least two relevant degree apprenticeship routes. (Owner: Student, Due: 25 October)
* **Action 3**: Book personal statement workshop. (Owner: Careers team, Due: 18 October)
* **Follow-up**: Review progress in three weeks.

This directly supports subsequent tracking.

### AI Feature 7: Workshop Generator
When the system identifies that 15 students share the same issue, the AI can generate a complete activity package:
* 45-minute lesson structure
* Facilitator notes
* Student exercises
* Examples
* Exit ticket
* Follow-up checklist

*Example (Apprenticeship Application Workshop)*:
* **Learning outcome**: Students can identify a suitable vacancy and complete the first stage of an application.
* **Sections**:
  1. Understanding vacancy requirements
  2. Translating part-time work into evidence
  3. Writing evidence-based answers
  4. Checking deadlines
  5. Personal action

This way, the product doesn't just tell the college "you should host a workshop"; it helps staff execute it immediately.

### AI Feature 8: Follow-up and Evidence Assistant
Based on the approved action plan, the AI generates:
* Student follow-up email or SMS drafts
* Adviser case notes
* Manager summaries
* Intervention evidence
* Overdue action alerts

*Example*:
*"You agreed to compare three occupational therapy courses before 25 October. Please record the entry requirements and one question you still have about each course."*

This part can use anonymous Demo data and does not need to send real messages.

---

## III. MVP AI Architecture
For a short-term implementation (e.g., within a week), a complex multi-agent system is not recommended. Using a single model with four distinct processing phases is sufficient:
1. **Extract**: Comprehend student responses and output structured JSON.
2. **Classify**: Identify goals, barriers, deadlines, and support requirements.
3. **Aggregate**: Search for cohort patterns and opportunities for collective intervention.
4. **Generate**: Create the Weekly Plan, Adviser Brief, Action Plan, etc.

### System Architecture
```
Student CSV / Check-in
        ↓
   PII Filter
        ↓
LLM Structured Extraction
        ↓
Rules and Capacity Engine
        ↓
Cohort Clustering
        ↓
LLM Intervention Generator
        ↓
   Human Review
        ↓
Action and Evidence Record
```
The most critical part is not the number of models, but having clear inputs and structured outputs at each step.

---

## IV. What the Product CANNOT Claim to Solve
Do not advertise that:
* AI decides what career is suitable for a student.
* AI predicts whether a student will become NEET (Not in Education, Employment, or Training).
* AI replaces Level 6 Career Advisers.
* AI automatically completes Personal Guidance.
* AI automatically guarantees Gatsby or Ofsted compliance.
* AI diagnoses students' mental health, domestic, or safeguarding risks.

These claims are difficult to verify and will raise concerns among judges regarding ethics, liability, and data protection.
**A more accurate product claim is**:
*AI does not make final career decisions, nor does it replace personal guidance. It helps the Career Team faster understand student needs, organize limited resources, prepare high-quality interventions, and record subsequent actions.*

---

## V. One-Sentence Value Propositions
* **For Judges**: *"Turn hundreds of student career check-ins into an adviser-ready weekly intervention plan."*
* **For Colleges**: *"See what your learners need, organise the right support, and prepare every guidance session without manually reviewing every response."*
* **For Career Advisers**: *"Spend less time sorting information and writing records, and more time guiding students."*

### Final Recommendation
You can add many AI features in the MVP, but they must revolve around the same core closed loop:
**Understand Needs → Find Patterns → Allocate Resources → Prepare Interventions → Generate Actions → Record Outcomes.**

The three most differentiated AI features are:
1. Translating free-text answers into structured career support needs.
2. Discovering cohort-wide barriers that can be addressed collectively.
3. Generating practical weekly intervention plans combined with Adviser capacity.

Adviser Briefs, Workshop Generators, Action Plans, and Evidence Notes can all expand around these three core features. This makes the product feel feature-rich without degrading into a messy collection of utilities.

---

## VI. Clarifications on Target Users & MIS Integration

### 1. MIS integration does not bypass data regulation; it triggers formal audits.
If the MVP directly connects to SIMS or another MIS and reads real student data, the product will handle:
* Student identity, courses, age, attendance, SEND, medical/support needs, consultation notes, and risk tags.

This shifts the product from an "anonymous prototype" to a formal EdTech data processing system.
Colleges must consider:
* Data processing agreements (DPA).
* Controller / Processor liabilities.
* Data minimization and access control.
* Retention and deletion policies.
* Sub-processors and model providers.
* Whether data is used for model training.
* International data transfers.
* Security testing.
* Data Protection Impact Assessments (DPIA) for student profiling or high-risk processing.

The DfE specifies that schools and colleges must consult their DPO from the start when using EdTech; high-risk processing (like profiling) usually requires a DPIA. Even if a vendor connects to an existing MIS, they should only access the data necessary for the specific purpose. (GOV.UK)
Also, replacing names with Student IDs is merely pseudonymization. If the college can still map the ID back to a specific student, it remains personal data under UK GDPR. Only truly anonymized data that cannot identify individuals is exempt. (ICO)

> [!IMPORTANT]
> MIS integration reduces manual uploads and duplicate entries, but it does not bypass data regulations.

### 2. The MVP should demonstrate "MIS Connectability" rather than connecting to a real MIS.
During the hackathon phase, the most reasonable solution is:
```
Mock SIMS / MIS Data
        ↓
Mock API or CSV Import
        ↓
Unified Data Schema
        ↓
AI Analysis & Operational Planning
```
In the UI, you can display:
* *"Connected source: SIMS Demo Environment"*
* *"Last synchronised: Today, 09:15"*

But in the backend, actually use:
* Synthetic student data.
* Student IDs that do not correspond to real individuals.
* Mock APIs or pre-formatted CSVs.

This demonstrates that the product *can* integrate with MIS in the future, without needing SIMS commercial API integration, college authorization, DPAs, DPIAs, real student data approval, or safety reviews during the hackathon.

#### MVP Data Fields
Only require:
* Student ID
* Programme
* Study level
* Intended destination
* Career readiness answers
* Main stated barrier
* Previous careers activity
* Upcoming transition deadline
* Requested support

Exclude for now:
* Real names, addresses, emails.
* Medical information, SEND details.
* Safeguarding notes, family background.
* Complete attendance logs.
During future official pilots, read-only MIS integration can be gradually introduced with fields decided by the College.

### 3. Capacity & Intervention Orchestrator (incorporating external resources)
The previous Intervention Plan Generator only considered internal Advisers, workshops, and student needs, which is incomplete.
FE College Career Teams naturally connect with:
* External Level 6 Career Advisers
* Careers Hubs
* National Careers Service
* Independent Training Providers
* Apprenticeship Providers
* Local employers
* Industry associations
* University outreach teams
* Workshop providers
* SEND specialist employment support agencies

Research shows that FE Colleges must leverage Careers Hubs, employers, and external support ecosystems to supplement internal resources instead of relying solely on internal advisers.
Therefore, AI Feature 4 is upgraded to **Capacity and Intervention Orchestrator**. It does not just generate internal schedules but answers:
*Which needs should be met by the internal team, and which should be delegated to tutors, group sessions, or external providers?*

### 4. How the system decides between internal and external delivery
* **System Inputs**:
  * *Student Needs*: 24 need apprenticeship application support, 12 need healthcare careers info, 8 need formal Personal Guidance, 6 need mock interviews.
  * *Internal Capacity*: 2 Career Advisers, 22 total hours this week, 1 Employer Engagement Officer, 2 internal workshops already scheduled.
  * *External Resource Catalog*: Local Careers Hub, Independent Level 6 Adviser, NHS Careers Outreach, Apprenticeship Training Provider, Local Chamber of Commerce, Mock Interview Volunteer Network.
* **System Outputs**:
  * *Internal Delivery*: 8 individual Personal Guidance sessions, 1 university options clinic.
  * *External Delivery Recommended*: NHS careers workshop for 12 learners, apprenticeship application session for 24 learners, employer-led mock interviews for 6 learners.
  * *Capacity Gap*: 11 qualified guidance hours still uncovered.
This truly addresses the "insufficient staffing" problem.

### 5. Additional AI capabilities for external partners
* **A. External Intervention Recommendation**: AI recommends service types based on student needs rather than directly recommending unverified specific companies.
  * *Need*: 18 engineering learners lack apprenticeship awareness.
  * *Recommended External Intervention*: Employer-led engineering apprenticeship workshop (60 mins, in-person). Suggested participants: local manufacturers and training providers.
  * *Production implementation*: Can connect to the college's approved provider directory.
* **B. Provider Brief Generator**: Automatically generates requirements for external providers.
  * *Audience*: 18 Level 2–3 engineering learners.
  * *Current barrier*: Limited understanding of apprenticeship recruitment and entry requirements.
  * *Required outcomes*: 
    1. Understand the application process.
    2. Interpret vacancy requirements.
    3. Identify realistic next actions.
  * *Preferred delivery*: 60-minute interactive workshop.
  * *Safeguarding*: No direct collection of learner personal data.
  * Staff do not need to write briefs from scratch.
* **C. Outreach Drafts**: Generates emails to employers, workshop invitations, service requirement statements, RFQs, follow-ups, and scheduling options. These must be approved by staff before sending. No auto-commit of budget or messaging.
* **D. Provider Matching**: In production, matches based on region, industry, service type, cost, delivery mode, DBS/Safeguarding checks, past college reviews, and availability. The MVP can pre-populate 10 mock providers to showcase matching logic.
* **E. Workshop Quality and Evidence**: After an event, generates attendance records, learner feedback, learning outcomes, follow-up actions, Gatsby evidence drafts, and provider performance records. This helps the college know if the external workshop actually resolved the students' issues.

### 6. Refined User Roles
* **Primary User: Careers Leader / Manager** (The core persona)
  * Cares about: How many students need support this week, whether the internal team has capacity, what can be done in groups vs. 1-to-1, what should be outsourced, what external providers should deliver, what gaps remain, and how to verify intervention completion.
  * The dashboard should be designed primarily for the Career Manager.
* **Secondary User: Career Adviser**
  * Uses: Student briefs, session prep, guidance notes, action plans, follow-ups, and human overrides.
* **Employer Engagement Officer**
  * Uses: External provider/employer matching, outreach briefs, workshop coordination, event logs, and provider performance reviews.
* **Student**
  * Action: Complete check-ins, view next steps, confirm actions, submit feedback. Students are data inputters, not primary system operators.

### 7. Complete Problem Definition for the MVP
The final problem definition is:
*FE Career Teams already have student data from MIS, check-ins, or assessment tools, but lack the manpower to quickly translate hundreds of student needs into internal services, external workshops, 1-to-1 guidance, and continuous follow-ups.*

The product operates in the middle layer:
```
MIS / FSQ / Careerpilot / Student Check-in
                    ↓
       Career Operations Copilot
                    ↓
Internal Adviser   Tutor/Group Session   External Provider
                    ↓
      Action, Follow-up, Evidence
```
It does not replace SIMS, Careerpilot, Compass+, or Purlos. It connects:
**Student Data → Need Comprehension → Resource Orchestration → Internal/External Delivery.**
