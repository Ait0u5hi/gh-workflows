# Security policy

## Reporting a vulnerability

**Do not open a public issue.** Public disclosure before a fix puts every user at risk.

Report privately through GitHub: go to the **Security** tab → **Report a vulnerability**. That opens
a private advisory visible only to the maintainers.

Please include:

- what the vulnerability lets an attacker do, and what access they need to start
- the affected version or commit
- **a reproduction a maintainer can run in one line** — a command, a script, an exact `file:line`.
  This is what makes a report actionable rather than a claim to be re-derived.

You can expect an acknowledgement within a week. If a report is valid, we will tell you when a fix
lands and credit you in the advisory unless you would rather stay anonymous.

## Scope

In scope: anything in this repository — code, workflows, and the dependency set it pins.

Out of scope: vulnerabilities in third-party services this project talks to (report those to the
service), and findings that require an attacker to already have local access to the machine running
it, unless the project is specifically supposed to defend that boundary.

## Supported versions

| Version | Supported |
|---|---|
| 1.x | yes |
| older | no |

## Handling of secrets

This project should never require a secret in the repository. Credentials come from the environment
or a secret store. If you find a committed credential, treat it as a vulnerability and report it
privately — and assume it is compromised and needs rotating, not just deleting.
