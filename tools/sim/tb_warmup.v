// Stage 2 gate for the warm up target.
//
// The recovered netlist has to behave as the design it came from: two 8 bit
// shift registers loaded serially, an adder, and success exactly when the two
// operands sum to 496.
//
// This checks every one of the 65536 operand pairs rather than a sample. An
// extraction defect that only shows on one carry pattern would survive a spot
// check, and the whole run costs a few seconds.
//
// No reset is needed between pairs: an 8 bit shift register is fully replaced
// after eight shifts, so the previous operands are gone by construction.

`timescale 1ns / 1ps

module tb_warmup;

  reg clk = 1'b0;
  reg rst_n = 1'b0;
  reg en = 1'b0;
  reg A = 1'b0;
  reg B = 1'b0;
  wire S;

  integer a, b;
  integer bit_index;
  integer successes = 0;
  integer mismatches = 0;
  reg expected;

  adder_demo dut (
      .clk(clk), .rst_n(rst_n), .en(en), .A(A), .B(B), .S(S)
  );

  always #5 clk = ~clk;

  task shift_pair(input [7:0] operand_a, input [7:0] operand_b);
    begin
      // Most significant bit first: the register shifts left and takes the
      // serial input at the bottom, so the first bit fed ends up at bit 7.
      for (bit_index = 7; bit_index >= 0; bit_index = bit_index - 1) begin
        @(negedge clk);
        A = operand_a[bit_index];
        B = operand_b[bit_index];
        en = 1'b1;
      end
      @(negedge clk);
      en = 1'b0;
      #1;
    end
  endtask

  initial begin
    rst_n = 1'b0;
    repeat (2) @(negedge clk);
    rst_n = 1'b1;
    @(negedge clk);

    for (a = 0; a < 256; a = a + 1) begin
      for (b = 0; b < 256; b = b + 1) begin
        shift_pair(a[7:0], b[7:0]);
        expected = ((a + b) == 496);
        if (S !== expected) begin
          mismatches = mismatches + 1;
          if (mismatches <= 10)
            $display("MISMATCH a=%0d b=%0d sum=%0d expected S=%b got S=%b",
                     a, b, a + b, expected, S);
        end
        if (S === 1'b1) successes = successes + 1;
      end
    end

    $display("");
    $display("pairs checked   %0d", 256 * 256);
    $display("success asserted %0d", successes);
    $display("mismatches      %0d", mismatches);
    // a and b are each at most 255, so a+b==496 needs a >= 241: fifteen pairs.
    if (mismatches == 0 && successes == 15)
      $display("RESULT: pass");
    else
      $display("RESULT: FAIL");
    $finish;
  end

endmodule
