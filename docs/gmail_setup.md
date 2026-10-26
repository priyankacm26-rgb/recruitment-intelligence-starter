# Gmail OAuth for local testing
1. In Google Cloud Console, create/select a project and enable Gmail API.
2. Configure OAuth consent screen and add your test Gmail address as a test user if required.
3. Create OAuth Client ID of type Desktop app and download JSON as `credentials.json` in project root.
4. Keep `credentials.json` and generated `token.json` private; `.gitignore` excludes them.
5. Start backend, then click Poll Gmail in the UI. Authorize read-only access in the browser.
6. Test only with a dedicated recruitment test mailbox first. This integration reads messages and does not delete them.

Only the first 25 matching messages are checked per poll in this starter. Production needs pagination, robust retry/backoff, file scanning, authentication, and review workflows. Job-portal accounts need provider-specific OAuth/IMAP access or forwarding; there is no universal job-portal connector.
