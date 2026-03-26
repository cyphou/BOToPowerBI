# Enterprise Migration Guide — Business Objects to Power BI

## 8-Phase Migration Methodology

### Phase 1: Discovery (Weeks 1–2)

**Objective**: Inventory all BO assets and understand the landscape.

- Connect to BO CMS via REST API: `python migrate.py --server https://bo:6405 --user admin`
- List all documents, universes, and folders
- Identify report owners, consumers, and refresh schedules
- Catalog data sources (databases, SAP systems, files)

**Deliverable**: BO asset inventory (CSV/Excel)

### Phase 2: Assessment (Weeks 3–4)

**Objective**: Score each report for migration complexity and readiness.

- Run portfolio assessment: `python migrate.py --server https://bo:6405 --global-assess`
- Review 9-category scoring per report (datasource, formula, visual, filter, model, interactivity, security, scope, crystal-specific)
- Classify reports: GREEN (automated), YELLOW (semi-automated), RED (manual)
- Estimate effort per report

**Deliverable**: Migration assessment report (HTML dashboard)

### Phase 3: Wave Planning (Weeks 5–6)

**Objective**: Group reports into migration waves by complexity and priority.

- **Wave 1**: Simple WebI reports (single data provider, basic charts, no prompts)
- **Wave 2**: Standard WebI reports (multiple queries, prompts, variables)
- **Wave 3**: Complex WebI (contexts, running calcs, input controls, alerters)
- **Wave 4**: Crystal Reports (formulas, parameters, subreports)
- **Wave 5**: Shared universes → shared semantic models
- **Wave 6**: Lumira and edge cases

**Deliverable**: Wave plan with report assignments and timeline

### Phase 4: Pilot (Weeks 7–10)

**Objective**: Migrate a pilot wave to validate the approach.

- Select 5–10 representative reports from Wave 1
- Run automated migration: `python migrate.py report.wid --output-dir pilot/`
- Validate output in Power BI Desktop
- Compare visuals side-by-side: source BO vs generated PBI
- Identify gaps and calibrate conversion rules

**Deliverable**: Pilot validation report, gap list, calibration adjustments

### Phase 5: Batch Migration (Weeks 11–20)

**Objective**: Migrate all reports in planned waves.

- Batch migrate per wave: `python migrate.py --batch wave1/ --output-dir output/wave1/`
- For shared universes: `python migrate.py --shared-model r1.wid r2.wid --model-name "Sales"`
- Run DAX optimization: `python migrate.py report.wid --no-optimize-dax` (disable if manual review preferred)
- Generate comparison reports for each workbook

**Deliverable**: Migrated .pbip projects per wave

### Phase 6: Validation (Weeks 21–24)

**Objective**: Validate all migrated reports against source BO reports.

- Open each .pbip in Power BI Desktop
- Compare data values (measure calculations, aggregations)
- Compare visual fidelity (chart types, formatting, layout)
- Validate prompts/slicers behavior
- Test drill-through navigation
- Validate security (RLS roles, row-level restrictions)

**Deliverable**: Validation sign-off per report

### Phase 7: Deployment (Weeks 25–28)

**Objective**: Deploy validated reports to Power BI Service / Fabric.

- Deploy to workspace: `python migrate.py report.wid --deploy WORKSPACE_ID`
- Deploy shared models: `python migrate.py --deploy-bundle WORKSPACE_ID`
- Configure gateways for on-premises data sources
- Set up refresh schedules (from BO schedule mapping)
- Configure row-level security
- Assign workspace permissions

**Deliverable**: Reports live in Power BI Service

### Phase 8: Cutover & Decommission (Weeks 29–32)

**Objective**: Transition users from BO to Power BI.

- Redirect BO report URLs to Power BI equivalents
- Train end users on Power BI navigation
- Monitor usage and adoption metrics
- Run parallel operation (BO + PBI) for 2–4 weeks
- Decommission BO reports after validation period

**Deliverable**: BO decommission plan, user training materials

## Key Decision Points

### Universe Strategy
- **Option A**: Convert each universe to a shared semantic model (recommended for multi-report reuse)
- **Option B**: Inline universe objects into per-report semantic models (simpler, but duplication)

### Data Connectivity
- **Option A**: Import mode (data copied to Power BI) — best for most scenarios
- **Option B**: DirectQuery (live queries) — for real-time needs or very large datasets
- **Option C**: Composite model — mix of Import + DirectQuery tables

### Security Model
- **Option A**: Migrate BO security profiles → RLS roles (recommended)
- **Option B**: Use workspace-level security only (simpler, less granular)
- **Option C**: Azure AD groups + RLS for enterprise-grade security

## Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Formula conversion gaps | Validate running calcs and context operators manually |
| Crystal binary parsing limitations | Use Crystal SDK for full extraction; manual re-creation for complex reports |
| Universe context complexity | Review ALLEXCEPT patterns; test with sample data |
| Performance regression | Compare query times BO vs PBI; optimize M queries and DAX |
| User adoption resistance | Provide training, side-by-side comparison, gradual rollout |
| Data source access | Ensure PBI gateway configured for all on-prem sources before migration |
