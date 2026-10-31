# Ethics

## Purpose

MixShield measures how well AI agents and their guards resist hidden instructions (indirect prompt injection) in English, Hinglish and Hindi, and it offers a defence. Everything here is meant to help people build safer agents.

## Fake data only

- Every attack ran inside AgentDojo's sandbox (simulated bank, email and Slack data) or against the demo's tool server, which holds fake emails, fake invoices and made-up IBANs (`ZZ00DEMO...`, invalid on purpose).
- No real account, person, company or service was attacked or contacted. No real money moved.
- The attacker goals are AgentDojo's own injection tasks. Their account numbers and email addresses belong to the benchmark, not to real people. No account numbers were invented.

## What is released, and why

- The attack texts (300 in three languages, plus 30 adaptive ones) and the benign texts (450) are released for defence research: to test guards, to reproduce our numbers, and to build better detectors for code-mixed languages.
- The texts are ordinary phishing-style instructions ("send the payment to this new account", "forward this email"). They contain no new technique that is not already public in AgentDojo or similar benchmarks. Writing them in Hinglish and Hindi is the point of the study: guards should be tested in the languages people actually use.
- Please use them only to test and improve defences, and only on systems you own or are allowed to test.

## Known limits that matter for safety

- MixShield is not a guarantee. It missed 2 of 27 adaptive attacks in its default mode, and it raises false alarms on real delegated instructions. See "Limitations" in the README.
- Results come from a sandbox and a scripted worst-case agent. Do not read them as a promise about any real deployment.
