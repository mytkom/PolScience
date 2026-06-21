# PolUni RAD-on ETL

A Java terminal application for extracting Polish higher education institution data from the official RAD-on / POL-on open-data APIs.

The application loads available filter dictionaries from RAD-on, lets the user choose filters in the terminal, sends POST requests for institution data, processes JSON responses with Jackson, and exports the final results into CSV files.

## Main features

- Fetches live dictionary values for:
    - voivodeships,
    - institution kinds,
    - institution statuses,
    - supervising institutions,
    - university types,
    - scientific institution types.
- Provides an interactive terminal menu for choosing filters.
- Builds dynamic request bodies based on selected options.
- Handles pagination by first reading `totalCount`, then requesting the full result set.
- Extracts general institution metadata from `portal-search`.
- Extracts yearly student count data from `report/execute`.
- Writes the results into:
    - `institutions.csv`
    - `institution_counts.csv`

## Technologies

- Java 17
- Jackson Databind
- Apache Commons CSV
- Lombok

## Output

The program creates two CSV files:

```text
institutions.csv
institution_counts.csv
````

`institutions.csv` contains general institution metadata, while `institution_counts.csv` contains yearly student counts for matched institutions.