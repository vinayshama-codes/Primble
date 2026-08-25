CORE V1 ENGINEERING PRINCIPLES
These rules apply throughout V1 and should guide implementation whenever a specific edge case is not separately described.
1. One Canonical Fact
A material fact should have one canonical representation that feeds:
Data Consistency;
SQS;
questionnaire/remediation;
generated forms;
Submission Brief;
E&O Audit Record.
Different features should not independently determine different versions of the same underlying fact.

2. Normalize Before Comparing
Primble should compare the meaning of facts, not raw extracted strings.
Formatting, terminology, abbreviations, document structure, and differing levels of specificity should be normalized before deciding that two values conflict.

3. Missing Does Not Mean No
Lack of evidence must never automatically become:
No
False
$0
0
None
another unsupported value
Primble should distinguish between information that is actually negative and information that simply was not found.

4. Do Not Silently Resolve Genuine Conflicts
If two materially incompatible values remain after normalization and scope matching, Primble should not arbitrarily select one.
The conflict should remain visible and route to the producer for resolution.

5. Do Not Ask the Client to Perform Insurance Classification
The client questionnaire is for factual business and exposure information.
It should not ask clients to determine:
NAICS;
SIC;
WC class codes;
GL class codes;
coverage symbols;
policy interpretation;
other insurance-specific classifications.

6. Preserve Provenance
Material information should remain traceable through:
Source → Extracted Value → Normalized Fact → Human Changes → Final Value → SQS / Output

7. Unknown Edge Cases Default to Producer Review
If Primble encounters a material field, exposure, condition, or conflict for which no V1 rule exists:
preserve the information;
do not invent a value;
do not invent a new SQS penalty;
do not automatically ask the client;
surface the item to the producer when necessary;
give it no new scoring effect until a rule is explicitly defined.
Needs Producer Review is preferable to Primble or engineering improvising an insurance rule.

NOTE : DOCUMENT PRECEDENCE
This master plan defines the changes and implementation requirements moving forward.
Where this document conflicts with the existing file : C:\Users\lenovo\OneDrive\Desktop\Primble\SQS_Scoring_Specification.docx.pdf, this document takes precedence.
Where this document does not modify an existing scoring rule, the current SQS specification remains authoritative.
Engineering should not introduce new insurance, scoring, validation, or questionnaire rules outside these documents without product approval.
