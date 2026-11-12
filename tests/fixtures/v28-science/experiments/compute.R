# V28 dependency-free scientific fixture: no package installer, no network.
values <- read.csv("data/measurements.csv")$value
stopifnot(length(values) == 5, is.numeric(values))
cat(sprintf("V28_R_PASS count=%d sum=%d mean=%d\n",
            length(values), sum(values), mean(values)))
png("outputs/plot.png", width=640, height=400)
plot(seq_along(values), values, type="b", pch=19,
     main="V28 reproducible scientific plot",
     xlab="Observation", ylab="Value")
dev.off()
