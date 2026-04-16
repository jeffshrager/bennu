# source("anal1.r")
library(zoo)

# -----------------------------
# Load TSV
# -----------------------------
df <- read.delim("lamp_controller_b.tsv", header=TRUE, sep="\t")

# Expect columns: methane, current (and maybe time)

# -----------------------------
# Parameters
# -----------------------------
ma_window <- 200   # tune this

# -----------------------------
# Detrend methane
# -----------------------------
methane_ma <- rollmean(df$methane, k = ma_window, fill = NA, align = "center")
methane_detrended <- df$methane - methane_ma

# -----------------------------
# Optional: smooth current
# -----------------------------
current_smooth <- rollmean(df$current, k = 5, fill = NA, align = "center")

# -----------------------------
# Clean (remove NA rows)
# -----------------------------
keep <- !is.na(methane_detrended) & !is.na(current_smooth)

methane_detrended <- methane_detrended[keep]
current_smooth    <- current_smooth[keep]

# -----------------------------
# Correlation
# -----------------------------
cor_val <- cor(methane_detrended, current_smooth)
print(paste("Correlation:", cor_val))

# -----------------------------
# Cross-correlation (lag!)
# -----------------------------
ccf(current_smooth, methane_detrended, lag.max = 200)

# -----------------------------
# Plot detrending sanity check
# -----------------------------
plot(df$methane, type="l", col="red", main="Methane detrending")
lines(methane_ma, col="blue")