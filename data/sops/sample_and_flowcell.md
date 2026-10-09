# Sample, flow cell, and run SOPs (example; replace with your lab's SOPs)

## SOP-DNA-01: Input DNA integrity
Check gDNA integrity on TapeStation (DIN of 7 or more) or Femto Pulse before library prep. Use wide-bore tips, mix by flicking or inversion, and never vortex HMW DNA. Keep freeze-thaw cycles to 2 or fewer. If the DIN is below 6, re-extract, or size-select with the Short Read Eliminator kit or a 0.45x bead cut. FFPE samples need repair (NEBNext FFPE Repair) and give short N50s by design.

## SOP-FC-01: Flow cell storage and check
Store flow cells at 2-8 C in their packaging and use them within 12 weeks of delivery. Always run a flow cell check before loading. R10.4.1 MinION flow cells are under warranty if fewer than 800 pores are active on arrival; file a claim within the warranty window with the flow cell check report. Keep a record of fridge temperature excursions.

## SOP-PRIME-01: Priming without bubbles
Open the priming port and draw back 20-30 uL to remove any air bubble, keeping the buffer covering the sensor array. Set the pipette 20 uL below the volume you are loading, and never push the plunger past the first stop. A bubble that crosses the sensor array destroys membranes in that region. This shows up as a sudden, spatially clustered drop in active pores within the first hours of the run.

## SOP-FLUSH-01: Nuclease flush and reload
If pores block mid-run (the channel state shows "unavailable" rising), pause the run and flush with the Flow Cell Wash Kit (EXP-WSH004) to digest the library. Wait 1 h, prime again, and reload fresh library. Recovery of more than 50% of pores confirms blocking rather than membrane damage. Up to 3 washes per flow cell.

## SOP-ENV-01: Device environment
Run MinION devices at an ambient 18-25 C with 5 cm of clearance around the vents. Don't place the device next to thermocyclers or other heat sources. Translocation speed should stay at about 400 bp/s at 34 C on the flow cell. Speeds consistently over 440 bp/s, or a temperature deviation over 1.5 C, mean the temperature control is struggling.

## SOP-BASECALL-01: Basecalling configuration
R10.4.1 data (FLO-MIN114) must be basecalled with an r10.4.1 e8.2 model, for example dna_r10.4.1_e8.2_400bps_sup@v5.0.0. Running an R9.4.1 model on R10 data gives mean Q below 10 and pass rates under 50% while the pore metrics stay normal. Re-basecall from POD5 with Dorado; the sample does not need re-sequencing.
