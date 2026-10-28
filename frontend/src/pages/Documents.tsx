import {
  Box,
  Card,
  CardContent,
  Grid,
  Typography,
} from "@mui/material";

export default function DashboardPage() {
  const metrics = [
    { title: "Documents", value: "12,483" },
    { title: "Threats Detected", value: "47" },
    { title: "Quarantined", value: "22" },
    { title: "Compliance Score", value: "98%" },
  ];

  return (
    <Box p={3}>
      <Typography variant="h4" gutterBottom>
        Security Dashboard
      </Typography>

      <Grid container spacing={3}>
        {metrics.map((metric) => (
          <Grid item xs={12} md={3} key={metric.title}>
            <Card>
              <CardContent>
                <Typography color="text.secondary">
                  {metric.title}
                </Typography>
                <Typography variant="h4">
                  {metric.value}
                </Typography>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  );
}