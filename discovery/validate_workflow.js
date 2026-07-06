export const meta = {
  name: 'validate-hiring-companies',
  description: 'Validate + enrich candidate employers (confirm current AI/SWE hiring, extract open positions, apply URLs, recruiting emails) for an auto-apply agent',
  phases: [
    { title: 'Validate', detail: 'web-verify each company is hiring AI/SWE now; extract positions + apply info' },
    { title: 'Recover', detail: 'retry the companies that could not be verified on pass 1' },
  ],
}

// args = array of candidate company objects OR a file path string to candidates_slim.json
let CANDIDATES = []
if (Array.isArray(args)) {
  CANDIDATES = args
} else if (args && args.companies) {
  CANDIDATES = args.companies
} else if (typeof args === 'string') {
  // file path: have an agent read it so we don't need FS access in the script
  const raw = await agent(`Read the file at this exact path and return ONLY the raw JSON array contents, nothing else: ${args}`, { label: 'load-candidates', effort: 'low' })
  try { CANDIDATES = JSON.parse(raw) } catch (_) { CANDIDATES = [] }
}

const SCHEMA = {
  type: 'object',
  additionalProperties: false,
  properties: {
    companies: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        properties: {
          company: { type: 'string' },
          domain: { type: 'string' },
          website: { type: 'string' },
          careers_url: { type: ['string', 'null'] },
          ats_platform: { type: ['string', 'null'] },
          application_email: { type: ['string', 'null'] },
          contact_email: { type: ['string', 'null'] },
          contact_page_url: { type: ['string', 'null'] },
          linkedin_url: { type: ['string', 'null'] },
          verification_status: { type: 'string', enum: ['verified_hiring', 'uncertain', 'not_hiring', 'not_found'] },
          verified: { type: 'boolean' },
          junior_roles_open: { type: 'boolean' },
          evidence_url: { type: ['string', 'null'] },
          confidence: { type: 'number' },
          location: { type: ['string', 'null'] },
          signal: { type: ['string', 'null'] },
          notes: { type: ['string', 'null'] },
          positions: {
            type: 'array',
            items: {
              type: 'object',
              additionalProperties: false,
              properties: {
                title: { type: 'string' },
                level: { type: ['string', 'null'] },
                location: { type: ['string', 'null'] },
                job_url: { type: ['string', 'null'] },
                apply_url: { type: ['string', 'null'] },
                employment_type: { type: ['string', 'null'] },
                posted_date: { type: ['string', 'null'] },
              },
              required: ['title'],
            },
          },
        },
        required: ['company', 'verification_status', 'verified', 'positions'],
      },
    },
  },
  required: ['companies'],
}

function chunk(arr, n) {
  const out = []
  for (let i = 0; i < arr.length; i += n) out.push(arr.slice(i, i + n))
  return out
}

function trim(c) {
  return { company: c.company, website: c.website || null, careers_url: c.careers_url || null, signal: c.signal || null }
}

function validatePrompt(batch, aggressive) {
  return `You are validating + enriching prospective EMPLOYERS for an agent that auto-applies to JUNIOR software jobs. You have WebSearch and WebFetch — USE THEM for every company (real lookups, never answer from memory).

TARGET ROLES: JUNIOR / entry-level / new-grad / associate / graduate Software Engineer, Software Developer, and junior AI/ML Engineer (roughly 0-2 years experience). Senior/staff/principal roles do NOT count for "junior_roles_open".

For EACH company below:
1. Find the official website + canonical "domain" (e.g. "acme.com"). ALWAYS set domain.
2. Find the careers/jobs page (careers_url). Identify the ATS: Greenhouse (boards.greenhouse.io / job-boards.greenhouse.io), Lever (jobs.lever.co), Ashby (jobs.ashbyhq.com), Workday (*.myworkdayjobs.com), or "other"/null.
3. Check whether the company CURRENTLY lists JUNIOR/entry-level SWE roles. Fetch the careers page / ATS board / LinkedIn Jobs to confirm. Set junior_roles_open accordingly.
4. Extract up to 8 currently-open relevant positions, each: title, level (junior/entry/new-grad/associate/mid/senior — your best read), location, job_url (listing URL), apply_url (direct apply link if visible), employment_type, posted_date. Prioritise junior roles. Real URLs only.
5. GATHER EVERY REACHABLE APPLICATION CHANNEL you can actually find (this is the whole point — the agent must be able to reach them):
   - apply_url on each position (the click-to-apply link)
   - application_email: recruiting/careers email (careers@/jobs@/talent@/recruiting@) if shown anywhere
   - contact_email: any general contact email
   - contact_page_url: the company's contact form / contact page
   - linkedin_url: the company's LinkedIn jobs or company page
   Only include channels you genuinely find; use null otherwise. Aim for AT LEAST ONE working channel per verified company.
6. Give evidence_url (a real URL proving current hiring) and confidence 0..1.
${aggressive ? '\nThese companies FAILED the first pass. Try harder: search "<company> careers", "<company> jobs", "<company> new grad software engineer", "<company> greenhouse OR lever OR ashby", fetch the careers page directly, and check LinkedIn Jobs. Spend extra effort before giving up.\n' : ''}
BE ADVERSARIAL: set verified=true + verification_status="verified_hiring" ONLY when you found a real, current/active SWE posting or careers listing WITH a URL. Otherwise "uncertain" (real company, hiring unconfirmed), "not_hiring" (real, no relevant roles), or "not_found" (cannot confirm it exists). NEVER fabricate URLs, emails, or positions — use null. Set junior_roles_open=true only if you actually saw a junior/entry-level/new-grad role.

Companies to validate (JSON):
${JSON.stringify(batch.map(trim), null, 1)}

Return the structured object (key "companies").`
}

function keyOf(c) {
  const d = (c.domain || c.website || '').toString().toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0].trim()
  return d || (c.company || '').toString().trim().toLowerCase()
}

phase('Validate')
log(`Validating ${CANDIDATES.length} candidate companies in batches of 4`)
const batches = chunk(CANDIDATES, 4)
const pass1 = await parallel(
  batches.map((b, i) => () =>
    agent(validatePrompt(b, false), { label: `validate:${i + 1}/${batches.length}`, phase: 'Validate', schema: SCHEMA, agentType: 'general-purpose' })
  )
)
const merged = new Map()
for (const r of pass1.filter(Boolean)) {
  for (const c of r.companies || []) merged.set(keyOf(c), c)
}

const unverified = [...merged.values()].filter((c) => !c.verified)
log(`Pass 1: ${merged.size} companies, ${merged.size - unverified.length} verified, ${unverified.length} to retry`)

if (unverified.length) {
  phase('Recover')
  const rbatches = chunk(unverified, 3)
  const pass2 = await parallel(
    rbatches.map((b, i) => () =>
      agent(validatePrompt(b, true), { label: `recover:${i + 1}/${rbatches.length}`, phase: 'Recover', schema: SCHEMA, agentType: 'general-purpose' })
    )
  )
  for (const r of pass2.filter(Boolean)) {
    for (const c of r.companies || []) {
      const k = keyOf(c)
      const prev = merged.get(k)
      // keep the better verdict (verified wins; else higher confidence)
      if (!prev || (c.verified && !prev.verified) || ((c.confidence || 0) > (prev.confidence || 0) && !prev.verified)) {
        merged.set(k, c)
      }
    }
  }
}

const out = [...merged.values()]
const verified = out.filter((c) => c.verified).length
const totalPos = out.reduce((s, c) => s + (c.positions ? c.positions.length : 0), 0)
log(`Done: ${out.length} companies, ${verified} verified_hiring, ${totalPos} positions extracted`)
return { companies: out, summary: { total: out.length, verified, positions: totalPos } }
