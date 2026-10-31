# SafeSpeak: An Anonymous School Concern Reporting and Classification System

## Introduction

### Background of the Project

Creating a safe and supportive school environment is essential to student well-being. However, students may hesitate to report bullying, mental health concerns, harassment, or campus safety issues because of fear of retaliation, judgment, or exposure of their identities.

Traditional reporting methods, such as physical suggestion boxes and face-to-face office visits, may discourage students from expressing their concerns. Furthermore, manually reviewing, organizing, and prioritizing submitted reports can result in administrative delays, especially when urgent incidents require immediate attention.

To address these challenges, **SafeSpeak: An Anonymous School Concern Reporting and Classification System** is proposed as a web-based platform that provides students with an accessible and confidential channel for reporting school-related concerns.

The system will utilize Natural Language Processing (NLP) to analyze submitted reports, identify their categories, and assess their urgency levels. Classified reports will be organized through an administrative dashboard, allowing authorized school personnel, such as guidance counselors and administrators, to review, prioritize, assign, and manage reported concerns more efficiently.

Through this approach, SafeSpeak aims to encourage responsible reporting, improve incident management, and support a safer and more responsive school environment.

---

## Statement of the Problem

Educational institutions face challenges in addressing student concerns, including bullying, harassment, mental health distress, and campus safety risks. Students may avoid reporting these incidents because of privacy concerns, fear of retaliation, or the lack of accessible reporting channels.

Additionally, traditional manual reporting processes can make it difficult for school personnel to organize, classify, and prioritize incoming concerns. This may result in delays in identifying urgent cases and providing appropriate interventions.

To address these challenges, the project aims to design, develop, and evaluate **SafeSpeak: An Anonymous School Concern Reporting and Classification System** to streamline concern reporting, automate report classification, and improve administrative case management.

### General Objective

To develop a web-based anonymous school concern reporting and classification system that utilizes Natural Language Processing (NLP) to categorize submitted concerns and identify their urgency levels.

### Specific Objectives

1. Develop a web-based reporting portal that allows students to submit school-related concerns anonymously.
2. Implement a Natural Language Processing (NLP) engine that analyzes submitted reports, identifies concern categories, and determines severity levels.
3. Integrate an administrative dashboard that displays incoming reports, provides urgency notifications, and supports efficient case management.
4. Establish role-based access control and secure audit logs to maintain data confidentiality and restrict unauthorized access.
5. Conduct User Acceptance Testing (UAT) with selected students and school personnel to evaluate usability, classification accuracy, and system performance.

---

## Significance of the Project

SafeSpeak is expected to provide practical benefits to the following stakeholders:

### Students
Provides students with an accessible and confidential platform where they can report bullying, harassment, mental health concerns, and safety-related incidents without publicly disclosing their identities.

### Guidance Counselors and Administrators
Helps authorized school personnel organize, classify, and prioritize submitted concerns. The system's classification and urgency assessment features can assist staff in identifying reports that may require immediate attention.

### School Leadership
Provides organized and anonymized reporting information that can help school leaders identify recurring concerns, recognize campus safety trends, and develop appropriate student welfare programs and institutional policies.

### Future Researchers and Developers
Serves as a reference for future studies and system development involving anonymous reporting platforms, Natural Language Processing, automated text classification, and school information systems.

---

## Alignment with Institutional Research Agenda and Sustainable Development Goals

### Institutional Research Agenda Alignment

SafeSpeak aligns with the institutional research priorities in **Information and Communications Technology (ICT), Campus Governance, and Student Welfare**. It applies web-based technologies and Natural Language Processing to modernize school concern reporting, improve incident classification, and support data-informed administrative decision-making.

### Sustainable Development Goals (SDGs)

**SDG 3: Good Health and Well-Being**

Supports student well-being by providing an accessible reporting channel for concerns involving bullying, mental health distress, and other situations that may require guidance or intervention.

**SDG 16: Peace, Justice, and Strong Institutions**

Promotes a safer and more accountable school environment by providing a structured reporting process that encourages students to raise concerns and enables authorized personnel to manage reported incidents.

---

## Scope and Limitations

### Scope of the Project

SafeSpeak will be developed as a web-based application intended for deployment within the school's digital network or an approved hosting environment. It will serve two primary user groups:

**1. Students**
- Access the web-based reporting portal.
- Submit school-related concerns anonymously.
- Select or provide details about the concern being reported.
- Attach supporting media when applicable.
- Receive a unique tracking code for submitted reports.
- Check the status of submitted reports using their tracking code.

**2. School Administrators and Guidance Counselors**
- Access the system through authenticated accounts.
- View and review submitted reports.
- Receive automatically classified reports and urgency assessments.
- Monitor incoming and pending concerns through an administrative dashboard.
- Assign reports to designated personnel.
- Update case statuses and document actions taken.
- Review report records and system activity through authorized audit logs.

### Core System Modules

| Module | Description |
|---|---|
| Anonymous Report Submission | Allows students to submit concerns without providing personal identity information. |
| NLP Classification Engine | Analyzes report content and automatically identifies the appropriate concern category. |
| Urgency Assessment Engine | Evaluates report content and assigns an estimated urgency level to assist in prioritization. |
| Administrative Dashboard | Displays submitted reports, classifications, urgency levels, and case statistics. |
| Case Management | Allows authorized personnel to review, assign, manage, and update reported concerns. |
| Status Tracking | Enables students to monitor their submitted reports using a unique tracking code. |
| Role-Based Access Control | Restricts system access and available functions according to assigned user roles. |
| Security and Audit Trail | Maintains protected system records and tracks authorized administrative activities. |

### Technology Stack

The proposed system will utilize the following technologies:

| Component | Proposed Technology |
|---|---|
| Frontend | HTML5, CSS3, JavaScript, Bootstrap |
| Backend | Python (FastAPI or Flask) |
| Database | PostgreSQL or MongoDB |
| NLP Processing | Python, NLTK, Scikit-learn |
| Classification | Machine Learning and Natural Language Processing |
| Development Environment | Visual Studio Code |
| Version Control | Git and GitHub |

*Note: The final technology stack will depend on the project's development requirements and implementation decisions.*

### Limitations of the Project

The following limitations define the boundaries of the current development phase:

1. **Anonymous Reporting:** The system is designed to avoid requiring students to disclose their identities. However, absolute anonymity cannot be guaranteed if identifying information is voluntarily included in report descriptions or uploaded attachments.

2. **NLP Classification Accuracy:** Automated classification and urgency assessment may not always correctly interpret the context, tone, or meaning of submitted reports. Human review by authorized school personnel will remain necessary.

3. **Internet and Hosting Requirements:** The system will operate as a web-based application hosted on the school's local network or an approved cloud server. Access will depend on the availability of the hosting environment and network connectivity.

4. **Emergency Response:** The system is intended for reporting and managing school concerns. It does not replace emergency hotlines, direct communication with emergency responders, or immediate intervention by school personnel.

5. **Excluded Integrations:** Active GPS tracking, IP tracing, direct emergency service or police integration, and native Android or iOS applications are excluded from the current development phase.

6. **Data and Access Restrictions:** Submitted reports and supporting attachments will only be accessible to authorized personnel according to their assigned permissions.

7. **Future Enhancements:** Additional integrations, advanced NLP capabilities, and mobile application support may be considered in future development phases.

---

## Project Status

**Development Status:** Planning / Proposed Development

SafeSpeak is currently intended as an academic software development project. Its features and implementation will be evaluated throughout the development and testing phases.

---

## License

This project is developed for academic purposes. Licensing and distribution terms may be established by the project developers.

---

## Disclaimer

SafeSpeak is intended to support school concern reporting and administrative case management. It is not a substitute for professional mental health services, counseling, emergency response, or formal school investigation procedures. Automated classifications and urgency assessments should be treated as decision-support information and must be reviewed by authorized school personnel.