' Local computation only. No network, filesystem, credentials or diagnostic URI output.
sub init()
    m.top.functionName = "SiloUIQrRun"
end sub

sub SiloUIQrRun()
    job = m.top.job
    matrix = []
    try
        matrix = SiloUISignInQr(job.uri)
    catch exception
        matrix = []
    end try
    m.top.result = {generation:job.generation,matrix:matrix}
end sub
