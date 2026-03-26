# Gap Analysis — BO to Power BI Migration

## Supported Conversions (✅)

### Web Intelligence
| Feature | Status | Notes |
|---------|--------|-------|
| Data providers (queries) | ✅ | Universe-based and freehand SQL |
| Variables (Measure) | ✅ | → DAX measures |
| Variables (Dimension) | ✅ | → Calculated columns or columns |
| Variables (Detail) | ✅ | → Columns associated with dimension |
| Report tabs | ✅ | → Report pages |
| Prompts | ✅ | → Slicers + parameter tables |
| Query filters | ✅ | → M query filters or DAX filters |
| Report filters | ✅ | → Page/visual-level filters |
| Charts (bar, line, pie) | ✅ | → PBI chart visuals |
| Tables | ✅ | → PBI table visual |
| Cross-tabs | ✅ | → PBI matrix visual |
| Breaks | ✅ | → Groups in matrix |
| Sorts | ✅ | → Visual sort configuration |
| Input controls | ✅ | → Slicers |
| Alerters | ✅ | → Conditional formatting rules |
| Calculations (150+ functions) | ✅ | → DAX expressions |

### Crystal Reports
| Feature | Status | Notes |
|---------|--------|-------|
| Formulas | ✅ | → DAX measures/calculated columns |
| Parameters | ✅ | → PBI parameters + slicers |
| Groups | ✅ | → Groups in visuals |
| Record selection | ✅ | → M query filter |
| Group selection | ✅ | → DAX filter |
| Running totals | ✅ | → CALCULATE window patterns |
| Subreports | ✅ | → Drill-through pages |
| Charts | ✅ | → PBI chart visuals |

### Universe
| Feature | Status | Notes |
|---------|--------|-------|
| Business layer objects | ✅ | → Columns + measures |
| Data foundation tables | ✅ | → M partitions |
| Joins | ✅ | → Relationships |
| Derived tables | ✅ | → M custom SQL |
| Contexts | ⚠️ | → ALLEXCEPT patterns (partial) |
| @Aggregate_Aware | ⚠️ | → Measure granularity (partial) |
| LOV (List of Values) | ✅ | → Parameter tables |

## Partial Support (⚠️)

| Feature | Gap | Workaround |
|---------|-----|-----------|
| **BO Contexts** | Complex chasm/fan trap resolution requires manual review | ALLEXCEPT template with manual column selection |
| **@Aggregate_Aware** | Multi-level aggregation routing needs per-measure DAX | Generate base measure; manual optimization for complex cases |
| **Crystal cross-tab** | Nested row/column groups partially supported | Matrix visual with manual group configuration |
| **Crystal subreport parameters** | Parameter linking partially mapped | Drill-through filter parameterization |
| **Dynamic alerters** | Multi-condition alerters simplified | Single conditional formatting rule per alerter |
| **WebI sections** | Nested sections lose exact layout | Flatten to visual groups on page |
| **Input control (slider)** | Numeric range input controls | PBI numeric slicer (range mode) |
| **Linked universes** | Multi-universe linking not automated | Manual relationship setup between semantic models |

## Not Supported (❌)

| Feature | Reason | Recommendation |
|---------|--------|----------------|
| **Crystal .rpt binary parsing** | Proprietary binary format — full SDK needed | Use Crystal Reports SDK or manual export to XML/PDF, then re-create |
| **BO scheduling (full)** | BO scheduling model differs significantly from PBI refresh | Map basic frequency; complex patterns need manual config |
| **BO Publications** | No direct PBI equivalent (targeted distribution) | Use PBI subscriptions + RLS per audience |
| **BO Discussions** | Collaboration feature with no PBI equivalent | Use Teams integration / Power BI comments |
| **BO Categories** | BO-specific organization taxonomy | Map to PBI workspace structure + tags |
| **BO Audit trail** | Server-level audit data not migrated | PBI admin API provides equivalent monitoring |
| **Universe connection pooling** | Server-side connection management | PBI gateway handles connection pooling |
| **Crystal formula timing** | `WhilePrintingRecords` / `WhileReadingRecords` evaluation | DAX is declarative — evaluation timing handled by engine |
| **Crystal Page N of M** | Crystal-specific pagination | PBI handles pagination differently (paginated reports for exact) |
| **Lumira Designer apps** | Custom SDK-based applications | Rebuild as Power BI embedded / Power Apps |
| **OLAP universes (BW)** | SAP BW-specific OLAP queries | Use PBI SAP BW connector directly |

## Formula Gap Summary

| Category | Total BO Functions | Supported | Gap |
|----------|-------------------|-----------|-----|
| Aggregation | 15 | 13 | 2 (Percentile, WeightedAvg) |
| Text | 25 | 22 | 3 (HTMLEncode, URLEncode, Multivalue) |
| Date | 30 | 26 | 4 (RelativeDate, FiscalCalendar, LastDayOfMonth complex) |
| Logic | 15 | 14 | 1 (Pattern matching with LIKE wildcards) |
| Math | 20 | 18 | 2 (Ceil with precision, Number formatting) |
| Null | 5 | 5 | 0 |
| Running | 5 | 3 | 2 (Running min/max with reset) |
| Context | 5 | 3 | 2 (Complex nested contexts) |
| Security | 3 | 3 | 0 |
| **Total** | **123** | **107** | **16 (87% coverage)** |

## Recommendations

1. **Start with WebI documents** — highest conversion fidelity
2. **Universe-first approach** — extract universe metadata to build the semantic model, then map reports
3. **Crystal Reports** — use the SDK or manual export for complex reports
4. **Lumira Designer** — rebuild as Power BI Embedded apps
5. **Validate running calculations** — BO running totals have sort-dependent behavior that may need manual DAX tuning
6. **Context review** — all context operator conversions should be manually validated
7. **@Aggregate_Aware** — review generated measures for correct granularity
