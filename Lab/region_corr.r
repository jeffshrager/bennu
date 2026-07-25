# Compute and print correlations between two fixed columns across a set
# of pre-defined row regions in an annotated TSV (from annotate_tsv.py).
# Edit the constants below, then: source("region_corr.r")

tsv_file <- "annotated.tsv"
col1 <- "raw_o3"
col2 <- "CH4"

# Name each region whatever you like — the name shows up in the
# "region" column of the printed table. Start/end are HH:MM:SS times
# matched against the TSV's TIME column (inclusive).
regions <- list(
  baseline = c("11:37:00", "11:37:30"),
  stim     = c("11:37:31", "11:38:15"),
  recovery = c("11:38:16", "11:38:45")
)

df <- read.delim(tsv_file, sep = "\t",
                  na.strings = c("NaN", "NA", ""),
                  stringsAsFactors = FALSE)

for (col in setdiff(names(df), c("TIME", "ping", "note"))) {
  df[[col]] <- suppressWarnings(as.numeric(df[[col]]))
}

results <- do.call(rbind, lapply(names(regions), function(name) {
  rng <- regions[[name]]
  rows <- which(df$TIME >= rng[1] & df$TIME <= rng[2])
  x <- df[[col1]][rows]
  y <- df[[col2]][rows]
  n <- sum(complete.cases(x, y))
  r <- if (n > 1) cor(x, y, use = "complete.obs") else NA
  data.frame(region = name, start = rng[1], end = rng[2], n = n, corr = r)
}))

print(results, row.names = FALSE)
