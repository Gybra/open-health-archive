# Security

Open Health Archive handles personal health data, so privacy problems are security
problems. Examples: health values or GPS points reaching logs or error messages, a
network request other than the OpenStreetMap tiles described in the README, files
written outside the folders the user chose, or an archive changed outside an import.

## Reporting

Report privately with the **Report a vulnerability** button on the repository's
Security tab; do not open a public issue. Never attach real health data, exports or
archives: reproduce the problem with a synthetic archive such as
`schema/fixtures/archive`.

Only the latest commit on `main` is supported.
