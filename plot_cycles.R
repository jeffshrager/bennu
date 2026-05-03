#!/usr/bin/env Rscript
# plot_cycles.R -- Methane over time with ON/OFF regions shaded
# Run from the experiment directory: Rscript /path/to/plot_cycles.R

dat <- read.table("cycles.tsv", header=TRUE, sep="\t", stringsAsFactors=FALSE)
dat$time_dt <- as.POSIXct(dat$time, format="%Y-%m-%dT%H:%M:%S", tz="America/Los_Angeles")

# Phase boundaries from run-length encoding
r      <- rle(dat$condition)
ends   <- cumsum(r$lengths)
starts <- c(1, head(ends, -1) + 1)

# Y axis: tight around the data, excluding extreme outliers
ylim <- quantile(dat$methane, c(0.002, 0.998)) + c(-0.005, 0.005)

png("methane_plot.png", width=1400, height=500, res=120)
par(mar=c(4, 4.5, 2, 1))

xlim <- range(dat$time_dt)

plot(dat$time_dt, dat$methane, type="n",
     xlab="Time", ylab="Methane (ppm)",
     xlim=xlim, ylim=ylim,
     main="Methane — ON (yellow) vs OFF (blue) cycles")

# Shaded ON/OFF regions
for (i in seq_along(r$lengths)) {
  col <- if (r$values[i] == "ON") "#FFF3A3" else "#C8E6FA"
  rect(dat$time_dt[starts[i]], ylim[1],
       dat$time_dt[ends[i]],   ylim[2],
       col=col, border=NA)
}

# Windspeed: smooth then rescale to methane y-range (uncalibrated, visual only)
ws_smooth <- filter(dat$windspeed, rep(1/60, 60), sides=2)  # 5-min rolling mean
ws_smooth[is.na(ws_smooth)] <- mean(dat$windspeed, na.rm=TRUE)
ws_scaled <- ylim[1] + (ws_smooth - min(ws_smooth, na.rm=TRUE)) /
             diff(range(ws_smooth, na.rm=TRUE)) * diff(ylim) * 0.25
lines(dat$time_dt, ws_scaled, col=adjustcolor("darkgreen", alpha.f=0.5), lwd=0.6)

# Methane trace
lines(dat$time_dt, dat$methane, col="gray30", lwd=0.6)

# Overall mean
abline(h=mean(dat$methane), col="firebrick", lty=2, lwd=1.2)

legend("topleft", bty="n",
       legend = c("ON", "OFF", "overall mean", "windspeed (rescaled)"),
       fill   = c("#FFF3A3", "#C8E6FA", NA, NA),
       border = c("gray60", "gray60", NA, NA),
       lty    = c(NA, NA, 2, 1),
       col    = c(NA, NA, "firebrick", adjustcolor("darkgreen", alpha.f=0.5)),
       lwd    = c(NA, NA, 1.2, 1.2))

dev.off()
cat("Written to methane_plot.png\n")
