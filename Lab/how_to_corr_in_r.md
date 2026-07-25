# Correlating columns of an annotated TSV in R

This shows how to load the TSV produced by `annotate_tsv.py` and compute a
correlation between any two columns over a chosen row range, e.g.

```r
corr("raw_o3", "CH4", 10000, 20000)
```

## 1. Read in the file

```r
df <- read.delim("annotated.tsv", sep = "\t",
                  na.strings = c("NaN", "NA", ""),
                  stringsAsFactors = FALSE)

# numeric columns (everything except TIME / ping / note, typically) need
# to actually be numeric — read.delim may leave them as character if any
# stray text slipped in
for (col in setdiff(names(df), c("TIME", "ping", "note"))) {
  df[[col]] <- suppressWarnings(as.numeric(df[[col]]))
}
```

Check it loaded as expected:

```r
str(df)
head(df)
```

## 2. Define a `corr()` helper

`corr(col1, col2, start, end)` correlates `col1` against `col2` over rows
`start:end` (1-based row numbers, matching R's default indexing — row 1 is
the first data row after the header, *not* counting the header itself).

```r
corr <- function(col1, col2, start, end, method = "pearson") {
  start <- max(1, start)
  end   <- min(nrow(df), end)
  x <- df[[col1]][start:end]
  y <- df[[col2]][start:end]
  cor(x, y, use = "complete.obs", method = method)
}
```

`use = "complete.obs"` drops rows where either value is `NA`/`NaN`, so
gaps (e.g. `raw_o3` rows that were never recoverable) don't error out the
calculation.

## 3. Use it

```r
corr("raw_o3", "CH4", 10000, 20000)
```

This returns a single Pearson correlation coefficient for `raw_o3` vs.
`CH4` over rows 10000–20000.

To see the relationship visually for the same range:

```r
with(df[10000:20000, ], plot(raw_o3, CH4))
```

To get the correlation matrix for several columns at once over a range:

```r
cols <- c("raw_o3", "CH4", "CH1")
cor(df[10000:20000, cols], use = "complete.obs")
```

## Notes

- `start`/`end` are **row numbers in the data frame**, not clock times. If
  you want to select rows by the `TIME` (HH:MM:SS) column instead, filter
  first:

  ```r
  sub <- subset(df, TIME >= "11:37:00" & TIME <= "11:38:00")
  cor(sub$raw_o3, sub$CH4, use = "complete.obs")
  ```

- If a column is constant (e.g. all-NA, or all-0) over the chosen range,
  `cor()` returns `NA` with a warning — that's expected, not a bug.
