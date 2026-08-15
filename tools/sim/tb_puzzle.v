// Stage 2 gate for the puzzle target.
//
// Replays example_inputs.vcd against the recovered netlist. The VCD records
// both what was driven in and what came back out, so this is a real functional
// check on the extraction rather than a smoke test: same inputs, same outputs,
// byte for byte.
//
// The tables are produced by tools/sim/make_puzzle_stimulus.py.
//   stimulus.txt  rst_n enable I  as they stood just before each rising edge
//   expected.txt  O success       as they stood just before the following one

`timescale 1ns / 1ps

module tb_puzzle;

  localparam integer CYCLES = 312;

  reg clk = 1'b0;
  reg rst_n = 1'b0;
  reg enable = 1'b0;
  reg I = 1'b0;
  wire [7:0] O;
  wire success;

  reg [2:0] stimulus [0:CYCLES-1];
  reg [8:0] expected [0:CYCLES-1];

  integer cycle;
  integer mismatches = 0;
  integer compared = 0;
  integer success_high = 0;
  reg [7:0] want_o;
  reg want_success;

  puzzle dut (
      .clk(clk), .rst_n(rst_n), .enable(enable), .I(I),
      .O(O), .success(success)
  );

  always #5 clk = ~clk;

  initial begin
    $readmemb("out/puzzle/stimulus.txt", stimulus);
    $readmemb("out/puzzle/expected.txt", expected);

    @(negedge clk);
    for (cycle = 0; cycle < CYCLES; cycle = cycle + 1) begin
      {rst_n, enable, I} = stimulus[cycle];
      @(posedge clk);
      @(negedge clk);

      want_o = expected[cycle][8:1];
      want_success = expected[cycle][0];

      if (^want_o !== 1'bx) begin
        compared = compared + 1;
        if (O !== want_o) begin
          mismatches = mismatches + 1;
          if (mismatches <= 10)
            $display("MISMATCH cycle %0d: O expected %b got %b", cycle, want_o, O);
        end
      end
      if (want_success !== 1'bx && success !== want_success) begin
        mismatches = mismatches + 1;
        if (mismatches <= 10)
          $display("MISMATCH cycle %0d: success expected %b got %b",
                   cycle, want_success, success);
      end
      if (success === 1'b1) success_high = success_high + 1;
    end

    $display("");
    $display("cycles replayed      %0d", CYCLES);
    $display("cycles compared on O %0d", compared);
    $display("mismatches           %0d", mismatches);
    $display("cycles with success  %0d", success_high);
    if (mismatches == 0 && success_high == 0)
      $display("RESULT: pass");
    else
      $display("RESULT: FAIL");
    $finish;
  end

endmodule
