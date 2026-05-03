#!/usr/bin/env Rscript
# analyze_cycles.R -- ON vs OFF t-tests on cycles.tsv
# Run from the experiment directory: Rscript /path/to/analyze_cycles.R

dat <- read.table("cycles.tsv", header=TRUE, sep="\t", stringsAsFactors=FALSE)

outfile <- "analysis.txt"
con <- file(outfile, open="wt")
emit <- function(...) { msg <- sprintf(...); cat(msg, "\n", sep=""); cat(msg, "\n", sep="", file=con) }

on  <- dat$methane[dat$condition == "ON"]
off <- dat$methane[dat$condition == "OFF"]

emit("ON  : n=%d  mean=%.4f  sd=%.4f", length(on),  mean(on),  sd(on))
emit("OFF : n=%d  mean=%.4f  sd=%.4f", length(off), mean(off), sd(off))
emit("")

result <- t.test(on, off, var.equal=FALSE)
p <- result$p.value
stars <- ifelse(p < 0.001, "***", ifelse(p < 0.01, "**", ifelse(p < 0.05, "*", "ns")))

emit("Welch t-test: t=%.4f  df=%.1f  p=%.6f  %s",
     result$statistic, result$parameter, p, stars)

# ---------------------------------------------------------------------------
# Within-pair analysis: correct for baseline drift
# Each ON phase is compared to the mean of its adjacent OFF phases,
# then a one-sample t-test asks whether those differences != 0.
# ---------------------------------------------------------------------------
emit("")
emit("--- Within-pair (drift-corrected) ---")
emit("")

r <- rle(dat$condition)
dat$phase_id <- rep(seq_along(r$lengths), r$lengths)

phase_means <- tapply(dat$methane,   dat$phase_id, mean)
phase_conds <- tapply(dat$condition, dat$phase_id, function(x) x[1])

phases <- data.frame(
  id        = as.integer(names(phase_means)),
  condition = as.character(phase_conds),
  mean_ch4  = as.numeric(phase_means),
  stringsAsFactors = FALSE
)
phases <- phases[order(phases$id), ]

on_ph  <- phases[phases$condition == "ON",  ]
off_ph <- phases[phases$condition == "OFF", ]

diffs <- mapply(function(on_id, on_mean) {
  adj <- off_ph$mean_ch4[off_ph$id %in% c(on_id - 1, on_id + 1)]
  if (length(adj) == 0) NA else on_mean - mean(adj)
}, on_ph$id, on_ph$mean_ch4)

diffs <- diffs[!is.na(diffs)]

emit("ON phase means:  mean=%.4f  sd=%.4f", mean(on_ph$mean_ch4),  sd(on_ph$mean_ch4))
emit("OFF phase means: mean=%.4f  sd=%.4f", mean(off_ph$mean_ch4), sd(off_ph$mean_ch4))
emit("ON-minus-adjacent-OFF diffs: n=%d  mean=%.4f  sd=%.4f",
     length(diffs), mean(diffs), sd(diffs))
emit("")

result2 <- t.test(diffs, mu=0)
p2 <- result2$p.value
stars2 <- ifelse(p2 < 0.001, "***", ifelse(p2 < 0.01, "**", ifelse(p2 < 0.05, "*", "ns")))
emit("One-sample t-test (diff vs 0): t=%.4f  df=%.1f  p=%.6f  %s",
     result2$statistic, result2$parameter, p2, stars2)

# ---------------------------------------------------------------------------
# Linear mixed model: methane ~ condition + time + (1 | phase_id)
# Models the drift as a fixed time covariate; phase as a random intercept.
# Requires lmerTest (which loads lme4) for Satterthwaite p-values.
# ---------------------------------------------------------------------------
emit("")
emit("--- Linear Mixed Model (drift + phase random effect) ---")
emit("")

library(lmerTest)

dat$time_hr <- as.numeric(as.POSIXct(dat$time, format="%Y-%m-%dT%H:%M:%S", tz="America/Los_Angeles"))
dat$time_hr <- (dat$time_hr - dat$time_hr[1]) / 3600  # hours from start
dat$condition <- factor(dat$condition, levels=c("OFF", "ON"))  # OFF = reference

lmm <- lmer(methane ~ condition + time_hr + (1 | phase_id), data=dat, REML=FALSE)
cf  <- summary(lmm)$coefficients

emit("Fixed effects:")
emit("  %-20s  %8s  %8s  %8s  %10s  %s",
     "term", "estimate", "std.err", "t", "p", "")
for (i in seq_len(nrow(cf))) {
  nm   <- rownames(cf)[i]
  est  <- cf[i, "Estimate"]
  se   <- cf[i, "Std. Error"]
  tv   <- cf[i, "t value"]
  pv   <- cf[i, "Pr(>|t|)"]
  sig  <- ifelse(pv < 0.001, "***", ifelse(pv < 0.01, "**", ifelse(pv < 0.05, "*", "ns")))
  emit("  %-20s  %8.5f  %8.5f  %8.4f  %10.6f  %s", nm, est, se, tv, pv, sig)
}

vc <- as.data.frame(VarCorr(lmm))
emit("")
emit("Random effects:  phase_id variance=%.6f  residual variance=%.6f",
     vc$vcov[vc$grp == "phase_id"], vc$vcov[vc$grp == "Residual"])

close(con)
cat(sprintf("\nWritten to %s\n", outfile))
