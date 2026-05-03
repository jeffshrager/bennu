#!/usr/bin/env Rscript
# run_analysis.R -- Filter cycles.tsv by time window, run stats + plot
# Usage: Rscript /path/to/run_analysis.R [--start HH:MM] [--end HH:MM]
# Times are wall-clock local time; midnight crossover handled automatically.

suppressPackageStartupMessages(library(lmerTest))

# --- Argument parsing --------------------------------------------------------
args <- commandArgs(trailingOnly=TRUE)
get_arg <- function(flag) {
  i <- which(args == flag)
  if (length(i) && i < length(args)) args[i + 1] else NULL
}
start_str <- get_arg("--start")
end_str   <- get_arg("--end")

# --- Load data ---------------------------------------------------------------
dat <- read.table("cycles.tsv", header=TRUE, sep="\t", stringsAsFactors=FALSE)
dat$time_dt <- as.POSIXct(dat$time, format="%Y-%m-%dT%H:%M:%S", tz="America/Los_Angeles")

# --- Time filtering ----------------------------------------------------------
tag <- "all"
if (!is.null(start_str) || !is.null(end_str)) {
  base_date <- as.Date(dat$time_dt[1], tz="America/Los_Angeles")

  start_dt <- if (!is.null(start_str))
    as.POSIXct(paste(base_date, start_str), format="%Y-%m-%d %H:%M", tz="America/Los_Angeles")
  else dat$time_dt[1]

  end_dt <- if (!is.null(end_str))
    as.POSIXct(paste(base_date, end_str), format="%Y-%m-%d %H:%M", tz="America/Los_Angeles")
  else dat$time_dt[nrow(dat)]

  if (end_dt <= start_dt) end_dt <- end_dt + 86400  # midnight crossover

  dat <- dat[dat$time_dt >= start_dt & dat$time_dt <= end_dt, ]
  tag <- paste0(gsub(":", "", start_str %||% "start"), "_",
                gsub(":", "", end_str   %||% "end"))
  cat(sprintf("Time window: %s to %s  (%d rows)\n", start_dt, end_dt, nrow(dat)))
}

if (nrow(dat) == 0) stop("No data in requested time window.")

# --- Output file names -------------------------------------------------------
out_txt <- sprintf("analysis_%s.txt", tag)
out_png <- sprintf("methane_plot_%s.png", tag)

# --- Emit helper (stdout + file) ---------------------------------------------
con <- file(out_txt, open="wt")
emit <- function(...) {
  msg <- sprintf(...)
  cat(msg, "\n", sep="")
  cat(msg, "\n", sep="", file=con)
}

# =============================================================================
# 1. Overall Welch t-test
# =============================================================================
on  <- dat$methane[dat$condition == "ON"]
off <- dat$methane[dat$condition == "OFF"]

emit("=== Overall Welch t-test ===")
emit("ON  : n=%d  mean=%.4f  sd=%.4f", length(on),  mean(on),  sd(on))
emit("OFF : n=%d  mean=%.4f  sd=%.4f", length(off), mean(off), sd(off))
emit("")
r1 <- t.test(on, off, var.equal=FALSE)
p1 <- r1$p.value
emit("t=%.4f  df=%.1f  p=%.6f  %s",
     r1$statistic, r1$parameter, p1,
     ifelse(p1<0.001,"***",ifelse(p1<0.01,"**",ifelse(p1<0.05,"*","ns"))))

# =============================================================================
# 2. Within-pair (drift-corrected) t-test
# =============================================================================
emit("")
emit("=== Within-pair (drift-corrected) ===")

r <- rle(dat$condition)
dat$phase_id <- rep(seq_along(r$lengths), r$lengths)
phase_means <- tapply(dat$methane,   dat$phase_id, mean)
phase_conds <- tapply(dat$condition, dat$phase_id, function(x) x[1])
phases <- data.frame(id=as.integer(names(phase_means)),
                     condition=as.character(phase_conds),
                     mean_ch4=as.numeric(phase_means),
                     stringsAsFactors=FALSE)
phases <- phases[order(phases$id), ]
on_ph  <- phases[phases$condition == "ON",  ]
off_ph <- phases[phases$condition == "OFF", ]

diffs <- mapply(function(oid, omean) {
  adj <- off_ph$mean_ch4[off_ph$id %in% c(oid-1, oid+1)]
  if (length(adj)==0) NA else omean - mean(adj)
}, on_ph$id, on_ph$mean_ch4)
diffs <- diffs[!is.na(diffs)]

emit("ON phase means:  mean=%.4f  sd=%.4f", mean(on_ph$mean_ch4), sd(on_ph$mean_ch4))
emit("OFF phase means: mean=%.4f  sd=%.4f", mean(off_ph$mean_ch4), sd(off_ph$mean_ch4))
emit("ON-minus-adjacent-OFF: n=%d  mean=%.4f  sd=%.4f", length(diffs), mean(diffs), sd(diffs))
emit("")
r2 <- t.test(diffs, mu=0)
p2 <- r2$p.value
emit("t=%.4f  df=%.1f  p=%.6f  %s",
     r2$statistic, r2$parameter, p2,
     ifelse(p2<0.001,"***",ifelse(p2<0.01,"**",ifelse(p2<0.05,"*","ns"))))

# =============================================================================
# 3. Linear mixed model
# =============================================================================
emit("")
emit("=== Linear Mixed Model: methane ~ condition + time_hr + (1|phase_id) ===")

dat$time_hr    <- as.numeric(dat$time_dt - dat$time_dt[1]) / 3600
dat$condition_f <- factor(dat$condition, levels=c("OFF","ON"))

lmm <- lmer(methane ~ condition_f + time_hr + (1|phase_id), data=dat, REML=FALSE)
cf  <- summary(lmm)$coefficients

emit("Fixed effects:")
emit("  %-20s  %8s  %8s  %8s  %10s", "term", "estimate", "std.err", "t", "p")
for (i in seq_len(nrow(cf))) {
  pv  <- cf[i, "Pr(>|t|)"]
  sig <- ifelse(pv<0.001,"***",ifelse(pv<0.01,"**",ifelse(pv<0.05,"*","ns")))
  emit("  %-20s  %8.5f  %8.5f  %8.4f  %10.6f  %s",
       rownames(cf)[i], cf[i,"Estimate"], cf[i,"Std. Error"], cf[i,"t value"], pv, sig)
}
vc <- as.data.frame(VarCorr(lmm))
emit("Random effects: phase variance=%.6f  residual=%.6f",
     vc$vcov[vc$grp=="phase_id"], vc$vcov[vc$grp=="Residual"])

close(con)
cat(sprintf("Written to %s\n", out_txt))

# =============================================================================
# Plot
# =============================================================================
ylim <- quantile(dat$methane, c(0.002, 0.998)) + c(-0.005, 0.005)
xlim <- range(dat$time_dt)

r   <- rle(dat$condition)   # recompute after potential refactoring
ends   <- cumsum(r$lengths)
starts <- c(1, head(ends,-1)+1)

ws_smooth <- filter(dat$windspeed, rep(1/60,60), sides=2)
ws_smooth[is.na(ws_smooth)] <- mean(dat$windspeed, na.rm=TRUE)
ws_scaled <- ylim[1] + (ws_smooth - min(ws_smooth,na.rm=TRUE)) /
             diff(range(ws_smooth,na.rm=TRUE)) * diff(ylim) * 0.25

png(out_png, width=1400, height=500, res=120)
par(mar=c(4,4.5,2,1))
plot(dat$time_dt, dat$methane, type="n",
     xlab="Time", ylab="Methane (ppm)", xlim=xlim, ylim=ylim,
     main=sprintf("Methane — ON (yellow) vs OFF (blue)  [%s]", tag))
for (i in seq_along(r$lengths)) {
  rect(dat$time_dt[starts[i]], ylim[1], dat$time_dt[ends[i]], ylim[2],
       col=if(r$values[i]=="ON") "#FFF3A3" else "#C8E6FA", border=NA)
}
lines(dat$time_dt, ws_scaled, col=adjustcolor("darkgreen", alpha.f=0.5), lwd=0.6)
lines(dat$time_dt, dat$methane, col="gray30", lwd=0.6)
abline(h=mean(dat$methane), col="firebrick", lty=2, lwd=1.2)
legend("topleft", bty="n",
       legend=c("ON","OFF","overall mean","windspeed (rescaled)"),
       fill=c("#FFF3A3","#C8E6FA",NA,NA), border=c("gray60","gray60",NA,NA),
       lty=c(NA,NA,2,1), col=c(NA,NA,"firebrick",adjustcolor("darkgreen",alpha.f=0.5)),
       lwd=c(NA,NA,1.2,1.2))
dev.off()
cat(sprintf("Written to %s\n", out_png))
