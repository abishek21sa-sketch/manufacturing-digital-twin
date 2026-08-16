# Data and Evidence Boundary

The included `data/external/orlib/jobshop1.txt` is a public OR-Library job-shop benchmark source. The repository defaults to the Fisher–Thompson `ft06` instance. OR-Library describes `jobshop1` as containing 82 test instances commonly cited in the literature.

Source page: `https://people.brunel.ac.uk/~mastjjb/jeb/orlib/jobshopinfo.html`
Source file: `https://people.brunel.ac.uk/~mastjjb/jeb/orlib/files/jobshop1.txt`

The benchmark supplies routing and deterministic processing-time data. It does **not** supply live plant telemetry, actual due dates, breakdown history, quality history, workers, material availability, or realized business outcomes. V1.0 therefore labels its factory definition `public_benchmark` and does not fabricate those missing fields.

Future external data follows:

`source -> adapter -> canonical FactoryModel/ManufacturingEvent -> validation -> event ledger -> twin state`
